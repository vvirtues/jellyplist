from collections import defaultdict
import time
from flask import Blueprint, Flask, jsonify, render_template, request, redirect, url_for, session, flash
from sqlalchemy import insert
from app import app, db,  jellyfin, functions, device_id,sp
from app.models import JellyfinUser, Playlist,Track,  playlist_tracks
from spotipy.exceptions import SpotifyException
from app.tasks import task_manager

from app.registry.music_provider_registry import MusicProviderRegistry
from jellyfin.objects import PlaylistMetadata
from app.routes import pl_bp, routes

@app.route('/jellyfin_playlists')
@functions.jellyfin_login_required
def jellyfin_playlists():
        playlists = jellyfin.get_playlists(session_token=functions._get_token_from_sessioncookie())
        playlists_by_provider = defaultdict(list)
        provider_playlists_data = {}

        for pl in playlists:
            from_db : Playlist | None = Playlist.query.filter_by(jellyfin_id=pl['Id']).first()
            if from_db and from_db.provider_playlist_id:
                pl_id = from_db.provider_playlist_id
                playlists_by_provider[from_db.provider_id].append(from_db)

                # 3. Fetch all Data from the provider using the get_playlist() method 
        for provider_id, playlists in playlists_by_provider.items():
            try:
                provider_client = MusicProviderRegistry.get_provider(provider_id)
            except ValueError:
                flash(f"Provider {provider_id} not found.", "error")
                continue

            combined_playlists = []
            for pl in playlists:
                # Use the cached provider_playlist_id to fetch the playlist from the provider
                provider_playlist = functions.get_cached_provider_playlist(pl.provider_playlist_id,pl.provider_id)
                #provider_playlist = provider_client.get_playlist(pl.provider_playlist_id)
                
                # 4. Convert the playlists to CombinedPlaylistData
                combined_data = functions.prepPlaylistData(provider_playlist)
                if combined_data:
                    combined_playlists.append(combined_data)

            provider_playlists_data[provider_id] = combined_playlists

                # 5. Display the resulting Groups in a template called 'monitored_playlists.html', one Heading per Provider
        return render_template('monitored_playlists.html', provider_playlists_data=provider_playlists_data,title="Jellyfin Playlists" , subtitle="Playlists you have added to Jellyfin")

@pl_bp.route('/addplaylist', methods=['POST'])
@functions.jellyfin_login_required
def add_playlist():
    playlist_id = request.form.get('item_id')  
    playlist_name = request.form.get('item_name')  
    additional_users = None
    if not playlist_id and request.data:
        # get data convert from json to dict
        data = request.get_json()
        playlist_id = data.get('item_id')
        playlist_name = data.get('item_name')
        additional_users = data.get('additional_users')
    # also get the provider id from the query params
    provider_id = request.args.get('provider')
    if not playlist_id:
        flash('No playlist ID provided')
        return ''
    # if no provider_id is provided, then show an error and return an empty string
    if not provider_id:
        flash('No provider ID provided')
        return ''
    try:
        # get the playlist from the correct provider
        provider_client = MusicProviderRegistry.get_provider(provider_id)
        playlist_data = provider_client.get_playlist(playlist_id)
        # Check if playlist already exists in the database, using the provider_id and the provider_playlist_id
        playlist = Playlist.query.filter_by(provider_playlist_id=playlist_id, provider_id=provider_id).first()
        # Add new playlist in the database if it doesn't exist
        # create the playlist via api key, with the first admin as 'owner' 
        if not playlist:
            fromJellyfin = jellyfin.create_music_playlist(functions._get_api_token(),playlist_data.name,[],functions._get_admin_id())['Id']
            playlist = Playlist(name=playlist_data.name, provider_playlist_id=playlist_id,provider_uri=playlist_data.uri,track_count = len(playlist_data.tracks), tracks_available=0, jellyfin_id = fromJellyfin, provider_id=provider_id)
            db.session.add(playlist)
            db.session.commit()
            if app.config['START_DOWNLOAD_AFTER_PLAYLIST_ADD']:
                task_manager.start_task('download_missing_tracks')
        # Get the logged-in user
        user : JellyfinUser = functions._get_logged_in_user()
        playlist.tracks_available = 0
        
        for idx, track_data in enumerate(playlist_data.tracks):
            
            track = Track.query.filter_by(provider_track_id=track_data.track.id, provider_id=provider_id).first()

            if not track:
                # Add new track if it doesn't exist
                track = Track(name=track_data.track.name, provider_track_id=track_data.track.id, provider_uri=track_data.track.uri, downloaded=False,provider_id = provider_id)
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
            flash(f'Playlist "{playlist_data.name}" successfully added','success')
            
        else:
            flash(f'Playlist "{playlist_data.name}" already in your list')
        item = {
            "name" : playlist_data.name,
            "id" : playlist_id,
            "can_add":False,
            "can_remove":True,
            "jellyfin_id" : playlist.jellyfin_id
        }
        if additional_users and session['is_admin']:
            db.session.commit()
            app.logger.debug(f"Additional users: {additional_users}")
            for user_id in additional_users:
                routes.add_jellyfin_user_to_playlist_internal(user_id,playlist.jellyfin_id)
            
        
        return render_template('partials/_add_remove_button.html',item= item)
            
            


    except Exception as e:
        flash(str(e))
        return ''
     

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
            "id" : playlist.provider_playlist_id,
            "can_add":True,
            "can_remove":False,
            "jellyfin_id" : playlist.jellyfin_id
        }
        return render_template('partials/_add_remove_button.html',item= item)
    except Exception as e:
        flash(f'Failed to remove item: {str(e)}')
    
@app.route('/refresh_playlist/<playlist_id>', methods=['GET'])
@functions.jellyfin_admin_required
def refresh_playlist(playlist_id):
    # get the playlist from the database using the playlist_id
    playlist = Playlist.query.filter_by(jellyfin_id=playlist_id).first()
    # if the playlist has a jellyfin_id, then fetch the playlist from Jellyfin
    if playlist.jellyfin_id:
        try:
            app.logger.debug(f"removing all tracks from playlist {playlist.jellyfin_id}")
            jellyfin_playlist = jellyfin.get_music_playlist(session_token=functions._get_api_token(), playlist_id=playlist.jellyfin_id)  
            jellyfin.remove_songs_from_playlist(session_token=functions._get_token_from_sessioncookie(), playlist_id=playlist.jellyfin_id, song_ids=[track for track in jellyfin_playlist['ItemIds']])
            ordered_tracks = db.session.execute(
                            db.select(Track, playlist_tracks.c.track_order)
                            .join(playlist_tracks, playlist_tracks.c.track_id == Track.id)
                            .where(playlist_tracks.c.playlist_id == playlist.id)
                            .order_by(playlist_tracks.c.track_order)
                        ).all()

            tracks = [track.jellyfin_id for track, idx in ordered_tracks if track.jellyfin_id is not None]
            #jellyfin.remove_songs_from_playlist(session_token=jellyfin_admin_token, playlist_id=playlist.jellyfin_id, song_ids=tracks)
            jellyfin.add_songs_to_playlist(session_token=functions._get_api_token(), user_id=functions._get_admin_id(), playlist_id=playlist.jellyfin_id, song_ids=tracks)
            # if the playlist is found, then update the playlist metadata
            provider_playlist = MusicProviderRegistry.get_provider(playlist.provider_id).get_playlist(playlist.provider_playlist_id)
            functions.update_playlist_metadata(playlist, provider_playlist)
            flash('Playlist refreshed')
            return jsonify({'success': True})
                
        except Exception as e:
            flash(f'Failed to refresh playlist: {str(e)}')
            return jsonify({'success': False})
        

@app.route('/wipe_playlist/<playlist_id>', methods=['DELETE'])
@functions.jellyfin_admin_required
def wipe_playlist(playlist_id):
    playlist = Playlist.query.filter_by(jellyfin_id=playlist_id).first()
    name = ""
    id = ""
    jf_id = ""
    try:
        jellyfin.remove_item(session_token=functions._get_api_token(), playlist_id=playlist_id)
    except Exception as e:
        flash(f"Jellyfin API Error: {str(e)}")
    if playlist:
        # Delete the playlist
        name = playlist.name
        id = playlist.provider_playlist_id
        jf_id = playlist.jellyfin_id
        db.session.delete(playlist)
        db.session.commit()
        flash('Playlist Deleted', category='info')
    item = {
        "name" : name,
        "id" : id,
        "can_add":True,
        "can_remove":False,
        "jellyfin_id" : jf_id
    }
    return render_template('partials/_add_remove_button.html',item= item)

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
    provider_track_id = request.args.get('provider_track_id')
    if search_query:
        results = jellyfin.search_music_tracks(functions._get_token_from_sessioncookie(), search_query)
        # Render only the search results section as response
        return render_template('partials/_jf_search_results.html', results=results,provider_track_id=  provider_track_id,search_query = search_query)
    return jsonify({'error': 'No search query provided'}), 400
from datetime import datetime,timezone
import subprocess

from sqlalchemy import insert
from app import celery, app, db, functions, sp, jellyfin, jellyfin_admin_token, jellyfin_admin_id

from app.models import JellyfinUser,Playlist,Track, user_playlists, playlist_tracks
import os
import redis
from celery import current_task
import asyncio
import requests

redis_client = redis.StrictRedis(host='redis', port=6379, db=0)
def acquire_lock(lock_name, expiration=60):
    return redis_client.set(lock_name, "locked", ex=expiration, nx=True)

def release_lock(lock_name):
    redis_client.delete(lock_name)

@celery.task(bind=True)
def update_all_playlists_track_status(self):
    lock_key = "update_all_playlists_track_status_lock"
    
    if acquire_lock(lock_key, expiration=600):  
        try:
            with app.app_context():
                playlists = Playlist.query.all()
                total_playlists = len(playlists)
                if not playlists:
                    app.logger.info("No playlists found.")
                    return {'status': 'No playlists found'}  

                app.logger.info(f"Found {total_playlists} playlists to update.")
                processed_playlists = 0

                for playlist in playlists:
                    total_tracks = 0
                    available_tracks = 0

                    for track in playlist.tracks:
                        total_tracks += 1
                        if track.filesystem_path and os.path.exists(track.filesystem_path):
                            available_tracks += 1
                        else:
                            track.downloaded = False
                            track.filesystem_path = None
                            db.session.commit()

                    playlist.track_count = total_tracks
                    playlist.tracks_available = available_tracks
                    db.session.commit()

                    processed_playlists += 1
                    progress = (processed_playlists / total_playlists) * 100
                    self.update_state(state='PROGRESS', meta={'current': processed_playlists, 'total': total_playlists, 'percent': progress})
                    if processed_playlists % 10 == 0 or processed_playlists == total_playlists:
                        app.logger.info(f"Processed {processed_playlists}/{total_playlists} playlists.")

                app.logger.info("All playlists' track statuses updated.")
                return {'status': 'All playlists updated', 'total': total_playlists, 'processed': processed_playlists}
        finally:
            release_lock(lock_key)
    else:
        app.logger.info("Skipping task. Another instance is already running.")
        return {'status': 'Task skipped, another instance is running'}


@celery.task(bind=True)
def download_missing_tracks(self):
    lock_key = "download_missing_tracks_lock"

    if acquire_lock(lock_key, expiration=1800): 
        try:
            app.logger.info("Starting track download job...")

            with app.app_context():
                spotdl_config = app.config['SPOTDL_CONFIG']
                cookie_file = spotdl_config['cookie_file']
                output_dir = spotdl_config['output']
                client_id = app.config['SPOTIPY_CLIENT_ID']
                client_secret = app.config['SPOTIPY_CLIENT_SECRET']
                search_before_download = app.config['SEARCH_JELLYFIN_BEFORE_DOWNLOAD']

                undownloaded_tracks = Track.query.filter_by(downloaded=False).all()
                total_tracks = len(undownloaded_tracks)
                if not undownloaded_tracks:
                    app.logger.info("No undownloaded tracks found.")
                    return {'status': 'No undownloaded tracks found'}

                app.logger.info(f"Found {total_tracks} tracks to download.")
                processed_tracks = 0
                failed_downloads = 0
                for track in undownloaded_tracks:
                    app.logger.info(f"Processing track: {track.name} ({track.spotify_track_id})")

                    # Check if the track already exists in the output directory
                    file_path = f"{output_dir.replace('{track-id}', track.spotify_track_id)}.mp3"

                    if os.path.exists(file_path):
                        app.logger.info(f"Track {track.name} is already downloaded at {file_path}. Marking as downloaded.")
                        track.downloaded = True
                        track.filesystem_path = file_path
                        db.session.commit()
                        continue

                    # If search_before_download is enabled, perform matching
                    if search_before_download:
                        app.logger.info(f"Searching for track in Jellyfin: {track.name}")
                        # Retrieve the Spotify track and preview URL
                        spotify_track = functions.get_cached_spotify_track(track.spotify_track_id)
                        preview_url = spotify_track.get('preview_url')
                        if not preview_url:
                            app.logger.error(f"Preview URL not found for track {track.name}.")
                            # Decide whether to skip or proceed to download
                            # For now, we'll proceed to download
                        else:
                            # Get the list of Spotify artist names
                            spotify_artists = [artist['name'] for artist in spotify_track['artists']]

                            # Perform the search in Jellyfin
                            match_found, jellyfin_file_path = jellyfin.search_track_in_jellyfin(
                                session_token=jellyfin_admin_token,
                                preview_url=preview_url,
                                song_name=track.name,
                                artist_names=spotify_artists
                            )
                            if match_found:
                                app.logger.info(f"Match found in Jellyfin for track {track.name}. Skipping download.")
                                track.downloaded = True
                                track.filesystem_path = jellyfin_file_path
                                db.session.commit()
                                continue
                            else:
                                app.logger.info(f"No match found in Jellyfin for track {track.name}. Proceeding to download.")

                    # Attempt to download the track using spotdl
                    try:
                        app.logger.info(f"Trying to download track: {track.name} ({track.spotify_track_id}), spotdl timeout = 90")
                        s_url = f"https://open.spotify.com/track/{track.spotify_track_id}"

                        command = [
                            "spotdl", "download", s_url,
                            "--output", output_dir,
                            "--cookie-file", cookie_file,
                            "--client-id", client_id,
                            "--client-secret", client_secret
                        ]

                        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                        if result.returncode == 0 and os.path.exists(file_path):
                            track.downloaded = True
                            track.filesystem_path = file_path
                            app.logger.info(f"Track {track.name} downloaded successfully to {file_path}.")
                        else:
                            app.logger.error(f"Download failed for track {track.name}.")
                            failed_downloads += 1
                            track.download_status = result.stdout[:2048]
                    except Exception as e:
                        app.logger.error(f"Error downloading track {track.name}: {str(e)}")
                        failed_downloads += 1
                        track.download_status = str(e)[:2048]

                    processed_tracks += 1
                    progress = (processed_tracks / total_tracks) * 100
                    db.session.commit()

                    self.update_state(state='PROGRESS', meta={
                        'current': processed_tracks,
                        'total': total_tracks,
                        'percent': progress,
                        'failed': failed_downloads
                    })

                app.logger.info("Track download job finished.")
                return {
                    'status': 'download_missing_tracks finished',
                    'total': total_tracks,
                    'processed': processed_tracks,
                    'failed': failed_downloads
                }
        finally:
            release_lock(lock_key)
    else:
        app.logger.info("Skipping task. Another instance is already running.")
        return {'status': 'Task skipped, another instance is running'}
    
@celery.task(bind=True)
def check_for_playlist_updates(self):
    lock_key = "check_for_playlist_updates_lock"
    
    if acquire_lock(lock_key, expiration=600):  
        try:
            app.logger.info('Starting playlist update check...')
            with app.app_context():
                playlists = Playlist.query.all()
                total_playlists = len(playlists)
                if not playlists:
                    app.logger.info("No playlists found.")
                    return {'status': 'No playlists found'}

                app.logger.info(f"Found {total_playlists} playlists to check for updates.")
                processed_playlists = 0

                for playlist in playlists:
                    playlist.last_updated = datetime.now( timezone.utc)
                    sp_playlist = sp.playlist(playlist.spotify_playlist_id)
                    
                    app.logger.info(f'Checking updates for playlist: {playlist.name}, s_snapshot = {sp_playlist['snapshot_id']}')
                    db.session.commit()
                    if sp_playlist['snapshot_id'] == playlist.snapshot_id:
                        app.logger.info(f'playlist: {playlist.name} , no changes detected, snapshot_id {sp_playlist['snapshot_id']}')
                        continue
                    try:
                        #region Check for updates
                        # Fetch all playlist data from Spotify
                        spotify_tracks = {}
                        offset = 0
                        playlist.snapshot_id = sp_playlist['snapshot_id']
                        while True:
                            playlist_data = sp.playlist_items(playlist.spotify_playlist_id, offset=offset, limit=100)
                            items = playlist_data['items']
                            spotify_tracks.update({offset + idx: track['track'] for idx, track in enumerate(items) if track['track']})
                            
                            if len(items) < 100:  # No more tracks to fetch
                                break
                            offset += 100  # Move to the next batch
                        
                        existing_tracks = {track.spotify_track_id: track for track in playlist.tracks}

                        # Determine tracks to add and remove
                        tracks_to_add = []
                        for idx, track_info in spotify_tracks.items():
                            if track_info:
                                track_id = track_info['id']
                                if track_id not in existing_tracks:
                                    track = Track.query.filter_by(spotify_track_id=track_id).first()
                                    if not track:
                                        track = Track(name=track_info['name'], spotify_track_id=track_id, spotify_uri=track_info['uri'], downloaded=False)
                                        db.session.add(track)
                                        db.session.commit()
                                        app.logger.info(f'Added new track: {track.name}')
                                    tracks_to_add.append((track, idx))

                        tracks_to_remove = [
                            existing_tracks[track_id] 
                            for track_id in existing_tracks 
                            if track_id not in {track['id'] for track in spotify_tracks.values() if track}
                        ]

                        if tracks_to_add or tracks_to_remove:
                            playlist.last_changed = datetime.now( timezone.utc)

                        # Add and remove tracks while maintaining order
                        
                        if tracks_to_add:
                            
                            for track, track_order in tracks_to_add:
                                stmt = insert(playlist_tracks).values(
                                    playlist_id=playlist.id,
                                    track_id=track.id,
                                    track_order=track_order
                                )
                                db.session.execute(stmt)
                            db.session.commit()
                            app.logger.info(f'Added {len(tracks_to_add)} tracks to playlist: {playlist.name}')

                        if tracks_to_remove:
                            for track in tracks_to_remove:
                                playlist.tracks.remove(track)
                            db.session.commit()
                            app.logger.info(f'Removed {len(tracks_to_remove)} tracks from playlist: {playlist.name}')
                        #endregion
                        
                        #region Update Playlist Items and Metadata
                        functions.update_playlist_metadata(playlist, sp_playlist)
                        ordered_tracks = db.session.execute(
                            db.select(Track, playlist_tracks.c.track_order)
                            .join(playlist_tracks, playlist_tracks.c.track_id == Track.id)
                            .where(playlist_tracks.c.playlist_id == playlist.id)
                            .order_by(playlist_tracks.c.track_order)
                        ).all()

                        tracks = [track.jellyfin_id for track, idx in ordered_tracks if track.jellyfin_id is not None]
                        jellyfin.add_songs_to_playlist(session_token=jellyfin_admin_token, user_id=jellyfin_admin_id, playlist_id=playlist.jellyfin_id, song_ids=tracks)
                        #endregion
                    except Exception as e:
                        app.logger.error(f"Error updating playlist {playlist.name}: {str(e)}")

                    processed_playlists += 1
                    progress = (processed_playlists / total_playlists) * 100

                    # Update progress
                    # self.update_state(state='PROGRESS', meta={'current': processed_playlists, 'total': total_playlists, 'percent': progress})

                    if processed_playlists % 10 == 0 or processed_playlists == total_playlists:
                        app.logger.info(f"Processed {processed_playlists}/{total_playlists} playlists.")

                return {'status': 'Playlist update check completed', 'total': total_playlists, 'processed': processed_playlists}
        finally:
            release_lock(lock_key)
    else:
        app.logger.info("Skipping task. Another instance is already running.")
        return {'status': 'Task skipped, another instance is running'}

@celery.task(bind=True)
def update_jellyfin_id_for_downloaded_tracks(self):
    lock_key = "update_jellyfin_id_for_downloaded_tracks_lock"
    
    if acquire_lock(lock_key, expiration=600):  # Lock for 10 minutes
        try:
            app.logger.info("Starting Jellyfin ID update for downloaded tracks...")

            with app.app_context():
                downloaded_tracks = Track.query.filter_by(downloaded=True, jellyfin_id=None).all()
                total_tracks = len(downloaded_tracks)
                if not downloaded_tracks:
                    app.logger.info("No downloaded tracks without Jellyfin ID found.")
                    return {'status': 'No tracks to update'}

                app.logger.info(f"Found {total_tracks} tracks to update with Jellyfin IDs.")
                processed_tracks = 0

                for track in downloaded_tracks:
                    app.logger.info(f"Fetching track details from Spotify: {track.name} ({track.spotify_track_id})")
                    search_results = jellyfin.search_music_tracks(jellyfin_admin_token,track.name)
                    spotify_track = None
                    
                    try:
                        best_match = None
                        for result in search_results:
                            # if there is only one result , assume it´s the right track.
                            if len(search_results) == 1:
                                best_match = result
                                break
                            # Ensure the result is structured as expected
                            jellyfin_track_name = result.get('Name', '').lower()
                            jellyfin_artists = [artist.lower() for artist in result.get('Artists', [])]
                            jellyfin_path = result.get('Path','')
                            if jellyfin_path == track.filesystem_path:
                                best_match = result
                                break
                            elif not spotify_track:
                                try:
                                    spotify_track = functions.get_cached_spotify_track(track.spotify_track_id)
                                    spotify_track_name = spotify_track['name']
                                    spotify_artists = [artist['name'] for artist in spotify_track['artists']]
                                    spotify_album = spotify_track['album']['name']
                                except Exception as e:
                                    app.logger.error(f"Error fetching track details from Spotify for {track.name}: {str(e)}")
                                    continue
                            # Compare name, artists, and album (case-insensitive comparison)
                            if (spotify_track_name.lower() == jellyfin_track_name and
                                set(artist.lower() for artist in spotify_artists) == set(jellyfin_artists) ):
                                best_match = result
                                break  # Stop when a match is found

                        # Step 4: If a match is found, update jellyfin_id
                        if best_match:
                            track.jellyfin_id = best_match['Id']
                            db.session.commit()
                            app.logger.info(f"Updated Jellyfin ID for track: {track.name} ({track.spotify_track_id})")
                        else:
                            app.logger.info(f"No matching track found in Jellyfin for {track.name}.")
                        
                        spotify_track = None
                        
                    except Exception as e:
                        app.logger.error(f"Error searching Jellyfin for track {track.name}: {str(e)}")

                    processed_tracks += 1
                    progress = (processed_tracks / total_tracks) * 100
                    self.update_state(state='PROGRESS', meta={'current': processed_tracks, 'total': total_tracks, 'percent': progress})

                app.logger.info("Finished updating Jellyfin IDs for all tracks.")
                return {'status': 'All tracks updated', 'total': total_tracks, 'processed': processed_tracks}

        finally:
            release_lock(lock_key)
    else:
        app.logger.info("Skipping task. Another instance is already running.")
        return {'status': 'Task skipped, another instance is running'}

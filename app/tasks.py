from datetime import datetime,timezone
import logging
import subprocess

from sqlalchemy import insert
from app import celery, app, db, functions, sp, jellyfin, jellyfin_admin_token, jellyfin_admin_id

from app.classes import AudioProfile
from app.models import JellyfinUser,Playlist,Track, user_playlists, playlist_tracks
import os
import redis
from celery import current_task,signals
import asyncio
import requests

redis_client = redis.StrictRedis(host='redis', port=6379, db=0)
def acquire_lock(lock_name, expiration=60):
    return redis_client.set(lock_name, "locked", ex=expiration, nx=True)

def release_lock(lock_name):
    redis_client.delete(lock_name)
def prepare_logger():
    FORMAT = "[%(asctime)s][%(filename)18s:%(lineno)4s - %(funcName)20s() ]  %(message)s" 
    logging.basicConfig(format=FORMAT)

@signals.celeryd_init.connect
def setup_log_format(sender, conf, **kwargs):
    FORMAT = "[%(asctime)s][%(filename)18s:%(lineno)4s - %(funcName)23s() ] %(levelname)7s - %(message)s"  
    
    conf.worker_log_format = FORMAT.strip().format(sender)
    conf.worker_task_log_format = FORMAT.format(sender)

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
                    app.logger.debug(f"Current Playlist: {playlist.name} [{playlist.id}:{playlist.provider_playlist_id}]" )
                    for track in playlist.tracks:
                        total_tracks += 1
                        if track.filesystem_path and os.path.exists(track.filesystem_path):
                            available_tracks += 1
                            track.downloaded = True
                            
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
                client_id = app.config['SPOTIFY_CLIENT_ID']
                client_secret = app.config['SPOTIFY_CLIENT_SECRET']
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
                    app.logger.info(f"Processing track: {track.name} [{track.provider_track_id}]")

                    # Check if the track already exists in the output directory
                    file_path = f"{output_dir.replace('{track-id}', track.provider_track_id)}.mp3"
                    # region search before download
                    if search_before_download:
                        app.logger.info(f"Searching for track in Jellyfin: {track.name}")
                        spotify_track = functions.get_cached_spotify_track(track.provider_track_id)
                        # at first try to find the track without fingerprinting it
                        best_match = find_best_match_from_jellyfin(track)
                        if best_match:
                            track.downloaded = True
                            if track.jellyfin_id != best_match['Id']:
                                track.jellyfin_id = best_match['Id']
                                app.logger.info(f"Updated Jellyfin ID for track: {track.name} ({track.provider_track_id})")
                            if track.filesystem_path != best_match['Path']:
                                track.filesystem_path = best_match['Path']
                            
                            db.session.commit()     
                            processed_tracks+=1   
                            continue                
                        
                        # region search with fingerprinting   
                        if spotify_track:                     
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
                        else:
                            app.logger.warning(f"spotify_track not set, see previous log messages")
                        #endregion
                                
                    #endregion 
                    
                    if os.path.exists(file_path):
                        app.logger.info(f"Track {track.name} is already downloaded at {file_path}. Marking as downloaded.")
                        track.downloaded = True
                        track.filesystem_path = file_path
                        db.session.commit()
                        continue

                    

                    # Attempt to download the track using spotdl
                    try:
                        app.logger.info(f"Trying to download track: {track.name} ({track.provider_track_id}), spotdl timeout = 90")
                        s_url = f"https://open.spotify.com/track/{track.provider_track_id}"
                        
                        command = [
                            "spotdl", "download", s_url,
                            "--output", output_dir,
                            "--client-id", client_id,
                            "--client-secret", client_secret
                        ]
                        if os.path.exists(cookie_file):
                            app.logger.debug(f"Found {cookie_file}, using it for spotDL")
                            command.append("--cookie-file")
                            command.append(cookie_file)

                        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                        if result.returncode == 0 and os.path.exists(file_path):
                            track.downloaded = True
                            track.filesystem_path = file_path
                            app.logger.info(f"Track {track.name} downloaded successfully to {file_path}.")
                        else:
                            app.logger.error(f"Download failed for track {track.name}.")
                            if result.stdout:
                                app.logger.error(f"\t stdout: {result.stdout}")
                            if result.stderr:
                                app.logger.error(f"\t stderr: {result.stderr} ")
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
            if app.config['REFRESH_LIBRARIES_AFTER_DOWNLOAD_TASK']:
                libraries = jellyfin.get_libraries(jellyfin_admin_token)
                for lib in libraries:
                    if lib['CollectionType'] == 'music':
                        jellyfin.refresh_library(jellyfin_admin_token, lib['ItemId'])
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
                    sp_playlist = sp.playlist(playlist.provider_playlist_id)
                    full_update = True
                    app.logger.info(f'Checking updates for playlist: {playlist.name}, s_snapshot = {sp_playlist['snapshot_id']}')
                    db.session.commit()
                    if sp_playlist['snapshot_id'] == playlist.snapshot_id:
                        app.logger.info(f'playlist: {playlist.name} , no changes detected, snapshot_id {sp_playlist['snapshot_id']}')
                        full_update = False
                    try:
                        #region Check for updates
                        # Fetch all playlist data from Spotify
                        if full_update:
                            spotify_tracks = {}
                            offset = 0
                            playlist.snapshot_id = sp_playlist['snapshot_id']
                            while True:
                                playlist_data = sp.playlist_items(playlist.provider_playlist_id, offset=offset, limit=100)
                                items = playlist_data['items']
                                spotify_tracks.update({offset + idx: track['track'] for idx, track in enumerate(items) if track['track']})
                                
                                if len(items) < 100:  # No more tracks to fetch
                                    break
                                offset += 100  # Move to the next batch
                            
                            existing_tracks = {track.provider_track_id: track for track in playlist.tracks}

                            # Determine tracks to add and remove
                            tracks_to_add = []
                            for idx, track_info in spotify_tracks.items():
                                if track_info:
                                    track_id = track_info['id']
                                    if track_id not in existing_tracks:
                                        track = Track.query.filter_by(provider_track_id=track_id).first()
                                        if not track:
                                            track = Track(name=track_info['name'], provider_track_id=track_id, provider_uri=track_info['uri'], downloaded=False)
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
    full_update_key = 'full_update_jellyfin_ids'
    if acquire_lock(lock_key, expiration=600):  # Lock for 10 minutes
        try:
            app.logger.info("Starting Jellyfin ID update for tracks...")

            with app.app_context():
                downloaded_tracks = Track.query.filter_by(downloaded=True, jellyfin_id=None).all()
                
                if acquire_lock(full_update_key, expiration=60*60*24):
                    app.logger.info(f"performing full update on jellyfin track ids. (Update tracks and playlists if better quality will be found)")
                    downloaded_tracks = Track.query.all()
                else:
                    app.logger.debug(f"doing update on tracks with downloaded = True and jellyfin_id = None")
                total_tracks = len(downloaded_tracks)
                if not downloaded_tracks:
                    app.logger.info("No downloaded tracks without Jellyfin ID found.")
                    return {'status': 'No tracks to update'}

                app.logger.info(f"Found {total_tracks} tracks to update ")
                processed_tracks = 0

                for track in downloaded_tracks:
                    try:
                        best_match = find_best_match_from_jellyfin(track)
                        if best_match:
                            track.downloaded = True
                            if track.jellyfin_id != best_match['Id']:
                                track.jellyfin_id = best_match['Id']
                                app.logger.info(f"Updated Jellyfin ID for track: {track.name} ({track.provider_track_id})")
                            if track.filesystem_path != best_match['Path']:
                                track.filesystem_path = best_match['Path']
                                app.logger.info(f"Updated filesystem_path for track: {track.name} ({track.provider_track_id})")
                                
                                
                            
                            db.session.commit()
                        else:
                            app.logger.warning(f"No matching track found in Jellyfin for {track.name}.")
                        
                        spotify_track = None
                        
                    except Exception as e:
                        app.logger.error(f"Error searching Jellyfin for track {track.name}: {str(e)}")

                    processed_tracks += 1
                    progress = (processed_tracks / total_tracks) * 100
                    self.update_state(state=f'{processed_tracks}/{total_tracks}: {track.name}', meta={'current': processed_tracks, 'total': total_tracks, 'percent': progress})

                app.logger.info("Finished updating Jellyfin IDs for all tracks.")
                return {'status': 'All tracks updated', 'total': total_tracks, 'processed': processed_tracks}

        finally:
            release_lock(lock_key)
    else:
        app.logger.info("Skipping task. Another instance is already running.")
        return {'status': 'Task skipped, another instance is running'}

def find_best_match_from_jellyfin(track: Track):
    app.logger.debug(f"Trying to find best match from Jellyfin server for track: {track.name}")
    search_results = jellyfin.search_music_tracks(jellyfin_admin_token, functions.get_longest_substring(track.name))
    spotify_track = None
    try:
        best_match = None
        best_quality_score = -1  # Initialize with the lowest possible score
        

        for result in search_results:
            
            app.logger.debug(f"Processing search result: {result['Id']}, Path = {result['Path']}")
            quality_score = compute_quality_score(result, app.config['FIND_BEST_MATCH_USE_FFPROBE'])
            try:
                spotify_track = functions.get_cached_spotify_track(track.provider_track_id)
                spotify_track_name = spotify_track['name'].lower()
                spotify_artists = [artist['name'].lower() for artist in spotify_track['artists']]
            except Exception as e:
                app.logger.error(f"\tError fetching track details from Spotify for {track.name}: {str(e)}")
                continue
            jellyfin_track_name = result.get('Name', '').lower()
            jellyfin_artists = [artist.lower() for artist in result.get('Artists', [])]
            
            if spotify_track and jellyfin_track_name and jellyfin_artists and spotify_artists:
                app.logger.debug("\tTrack details to compare: ")
                app.logger.debug(f"\t\tJellyfin-Trackname : {jellyfin_track_name}")
                app.logger.debug(f"\t\t Spotify-Trackname : {spotify_track_name}")
                app.logger.debug(f"\t\t  Jellyfin-Artists : {jellyfin_artists}")
                app.logger.debug(f"\t\t   Spotify-Artists : {spotify_artists}")
                if len(search_results) == 1:
                    app.logger.debug(f"\tOnly 1 search_result: {result['Id']} ({app.config['JELLYFIN_SERVER_URL']}/web/#/details?id={result['Id']})")
                    
                    if (spotify_track_name.lower() == jellyfin_track_name and
                        set(artist.lower() for artist in spotify_artists) == set(jellyfin_artists)):
                        
                        app.logger.debug(f"\tQuality score for track {result['Name']}: {quality_score} [{result['Path']}]")
                        best_match = result
                        break
                
                
                if (spotify_track_name.lower() == jellyfin_track_name and
                    set(artist.lower() for artist in spotify_artists) == set(jellyfin_artists)):
                    app.logger.debug(f"\tQuality score for track {result['Name']}: {quality_score} [{result['Path']}]")
                    
                    if quality_score > best_quality_score:
                        best_match = result
                        best_quality_score = quality_score

        return best_match
    except Exception as e:
        app.logger.error(f"Error searching Jellyfin for track {track.name}: {str(e)}")
        return None

def compute_quality_score(result, use_ffprobe=False) -> float:
    """
    Compute a quality score for a track based on its metadata or detailed analysis using ffprobe.
    """
    score = 0
    container = result.get('Container', '').lower()
    if container == 'flac':
        score += 100
    elif container == 'wav':
        score += 50
    elif container == 'mp3':
        score += 10
    elif container == 'aac':
        score += 5
    
    if result.get('HasLyrics'):
        score += 10
    
    runtime_ticks = result.get('RunTimeTicks', 0)
    score += runtime_ticks / 1e6

    if use_ffprobe:
        path = result.get('Path')
        if path:
            profile = AudioProfile.analyze_audio_quality_with_ffprobe(path)
            ffprobe_score = profile.compute_quality_score()
            score += ffprobe_score
        else:
            app.logger.warning(f"No valid file path for track {result.get('Name')} - Skipping ffprobe analysis.")
    
    return score

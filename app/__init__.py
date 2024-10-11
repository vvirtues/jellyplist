import atexit
from logging.handlers import RotatingFileHandler
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from celery import Celery
from config import Config
from jellyfin.client import JellyfinClient
import logging
from spotdl import Spotdl
from spotdl.utils.config import DEFAULT_CONFIG

app = Flask(__name__, template_folder="../templates")
app.config.from_object(Config)
sp = spotipy.Spotify(auth_manager= SpotifyClientCredentials(client_id=app.config['SPOTIPY_CLIENT_ID'], client_secret=app.config['SPOTIPY_CLIENT_SECRET']))
jellyfin = JellyfinClient(app.config['JELLYFIN_SERVER_URL'])
spotdl_config = DEFAULT_CONFIG

spotdl_config['cookie_file'] = '/jellyplist/cookies.txt'
spotdl_config['output'] = '/storage/media/music/_spotify_playlists/{track-id}'
spotdl_config['threads'] = 12
spotdl = Spotdl( app.config['SPOTIPY_CLIENT_ID'],app.config['SPOTIPY_CLIENT_SECRET'], downloader_settings=spotdl_config)



# Configurations
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://jellyplist:jellyplist@192.168.178.14/jellyplist'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Configure Logging
log_file = 'app.log'
handler = RotatingFileHandler(log_file, maxBytes=100000, backupCount=3)  # 100KB per file, with 3 backups
handler.setLevel(logging.INFO)

app.logger.info('Application started')

from app import routes, models
from app.models import JellyfinUser,Track,Playlist
from apscheduler.schedulers.background import BackgroundScheduler



# Initialize the scheduler
scheduler = BackgroundScheduler()

def update_all_playlists_track_status():
    """
    Update track_count and tracks_available for all playlists in the database.
    For each track, check if the file exists on the filesystem. If not, reset the downloaded flag and filesystem_path.
    """
    with app.app_context():
        playlists = Playlist.query.all()

        if not playlists:
            app.logger.info("No playlists found.")
            return

        for playlist in playlists:
            total_tracks = 0
            available_tracks = 0

            for track in playlist.tracks:
                total_tracks += 1
                
                # Check if the file exists
                if track.filesystem_path and os.path.exists(track.filesystem_path):
                    available_tracks += 1
                else:
                    # If the file doesn't exist, reset the 'downloaded' flag and 'filesystem_path'
                    track.downloaded = False
                    track.filesystem_path = None
                    db.session.commit()

            # Update playlist fields
            playlist.track_count = total_tracks
            playlist.tracks_available = available_tracks

            db.session.commit()

        app.logger.info("All playlists' track statuses updated.")

def download_missing_tracks():
    app.logger.info("Starting track download job...")
    with app.app_context():
        # Get all tracks that are not downloaded
        undownloaded_tracks = Track.query.filter_by(downloaded=False).all()

        if not undownloaded_tracks:
            app.logger.info("No undownloaded tracks found.")
            return

        for track in undownloaded_tracks:
            app.logger.info(f"Trying to downloading track: {track.name} ({track.spotify_track_id})")

            try:
                # Download track using spotDL
                s_url = f"https://open.spotify.com/track/{track.spotify_track_id}"
                search = spotdl.search([s_url])
                if search:
                    song = search[0]
                    dl_request = spotdl.download(song)
                    # Assuming spotDL downloads files to the './downloads' directory, set the filesystem path
                    file_path = dl_request[1].__str__()  # Adjust according to naming conventions

                    if os.path.exists(file_path):
                        # Update the track's downloaded status and filesystem path
                        track.downloaded = True
                        track.filesystem_path = file_path
                        db.session.commit()

                        app.logger.info(f"Track {track.name} downloaded successfully to {file_path}.")
                    else:
                        app.logger.error(f"Download failed for track {track.name}: file not found.")
                else:
                    app.logger.warning(f"{track.name} ({track.spotify_track_id}) not Found")

            except Exception as e:
                app.logger.error(f"Error downloading track {track.name}: {str(e)}")

        app.logger.info("Track download job finished.")
        update_all_playlists_track_status()

def check_for_playlist_updates():
    app.logger.info('Starting playlist update check...')
    with app.app_context():
        try:
            playlists = Playlist.query.all()  # Get all users
            for playlist in playlists:
                app.logger.info(f'Checking updates for playlist: {playlist.name}')
                try:
                    # Fetch the latest data from the Spotify API
                    playlist_data = sp.playlist(playlist.spotify_playlist_id)
                    spotify_tracks = {track['track']['id']: track['track'] for track in playlist_data['tracks']['items']}
                    existing_tracks = {track.spotify_track_id: track for track in playlist.tracks}

                    # Tracks to add
                    tracks_to_add = []
                    for track_id, track_info in spotify_tracks.items():
                        if track_id not in existing_tracks:
                            track = Track.query.filter_by(spotify_track_id=track_id).first()
                            if not track:
                                track = Track(name=track_info['name'], spotify_track_id=track_id, spotify_uri=track_info['uri'],downloaded= False)
                                db.session.add(track)
                                db.session.commit()
                                app.logger.info(f'Added new track: {track.name}')
                            tracks_to_add.append(track)

                    # Tracks to remove
                    tracks_to_remove = [existing_tracks[track_id] for track_id in existing_tracks if track_id not in spotify_tracks]

                    if tracks_to_add:
                        for track in tracks_to_add:
                            playlist.tracks.append(track)
                        db.session.commit()
                        app.logger.info(f'Added {len(tracks_to_add)} tracks to playlist: {playlist.name}')

                    if tracks_to_remove:
                        for track in tracks_to_remove:
                            playlist.tracks.remove(track)
                        db.session.commit()
                        app.logger.info(f'Removed {len(tracks_to_remove)} tracks from playlist: {playlist.name}')

                except Exception as e:
                    app.logger.error(f"Error updating playlist {playlist.name}: {str(e)}")

        except Exception as e:
            app.logger.error(f"Error in check_for_playlist_updates: {str(e)}")

    app.logger.info('Finished playlist update check.')
    update_all_playlists_track_status()



# Add the job to run every 10 minutes (customize the interval as needed)
#scheduler.add_job(download_missing_tracks, 'interval', seconds=30, max_instances=1)
#scheduler.add_job(check_for_playlist_updates, 'interval', minutes=10, max_instances=1)
#download_missing_tracks()
#check_for_playlist_updates()
# Start the scheduler
scheduler.start()

# Ensure the scheduler shuts down properly when the app stops
atexit.register(lambda: scheduler.shutdown())
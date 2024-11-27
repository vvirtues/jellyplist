from logging.handlers import RotatingFileHandler
import os
import time
from flask_socketio import SocketIO

import sys
from flask import Flask, has_request_context
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from psycopg2 import OperationalError
import spotipy
from spotipy.oauth2 import  SpotifyClientCredentials
from celery import Celery
from celery.schedules import crontab
from sqlalchemy import create_engine
from config import Config
from jellyfin.client import JellyfinClient
import logging
from spotdl.utils.config import DEFAULT_CONFIG
from flask_caching import Cache
from .version import __version__


def check_db_connection(db_uri, retries=5, delay=5):
    """
    Check if the database is reachable.

    Args:
        db_uri (str): The database URI.
        retries (int): Number of retry attempts.
        delay (int): Delay between retries in seconds.

    Raises:
        SystemExit: If the database is not reachable after retries.
    """
    for attempt in range(1, retries + 1):
        try:
            engine = create_engine(db_uri)
            connection = engine.connect()
            connection.close()
            app.logger.info("Successfully connected to the database.")
            return
        except OperationalError as e:
            app.logger.error(f"Database connection failed on attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                app.logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                app.logger.critical("Could not connect to the database. Exiting application.")
                sys.exit(1)

# Celery setup
def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['result_backend'],  
        broker=app.config['CELERY_BROKER_URL'],
        include=['app.tasks']  
    )
    celery.conf.update(app.config)
    # Configure Celery Beat schedule
    celery.conf.beat_schedule = {
        'download-missing-tracks-schedule': {
            'task': 'app.tasks.download_missing_tracks',
            'schedule': crontab(minute='30'),  
        },
        'check-playlist-updates-schedule': {
            'task': 'app.tasks.check_for_playlist_updates',
            'schedule': crontab(minute='25'),  
        },
        'update_all_playlists_track_status-schedule': {
            'task': 'app.tasks.update_all_playlists_track_status',
            'schedule': crontab(minute='*/5'),  
            
        },
        'update_jellyfin_id_for_downloaded_tracks-schedule': {
            'task': 'app.tasks.update_jellyfin_id_for_downloaded_tracks',
            'schedule': crontab(minute='*/10'),  
            
        }
    }
    
    celery.conf.timezone = 'UTC'
    return celery

# Why this ? Because we are using the same admin login for web, worker and beat we need to distinguish the device_id´s
device_id = f'JellyPlist_{'_'.join(sys.argv)}'

# Initialize Flask app
app = Flask(__name__, template_folder="../templates", static_folder='../static')
# log_file = 'app.log'
# handler = RotatingFileHandler(log_file, maxBytes=100000, backupCount=3)
# handler.setLevel(logging.DEBUG)
# handler.setFormatter(log_formatter)
# stream_handler = logging.StreamHandler(sys.stdout)
# stream_handler.setLevel(logging.DEBUG)
# stream_handler.setFormatter(log_formatter)


# # app.logger.addHandler(handler)
# app.logger.addHandler(stream_handler)


app.config.from_object(Config)
for handler in app.logger.handlers:
    app.logger.removeHandler(handler)

log_level = getattr(logging, app.config['LOG_LEVEL'], logging.INFO)  # Default to DEBUG if invalid
app.logger.setLevel(log_level)

FORMAT = "[%(asctime)s][%(filename)18s:%(lineno)4s - %(funcName)20s() ] %(levelname)7s - %(message)s" 
logging.basicConfig(format=FORMAT)

Config.validate_env_vars()
cache = Cache(app)


# Spotify, Jellyfin, and Spotdl setup
app.logger.info(f"setting up spotipy")
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=app.config['SPOTIFY_CLIENT_ID'],
    client_secret=app.config['SPOTIFY_CLIENT_SECRET']
))

app.logger.info(f"setting up jellyfin client, BaseUrl = {app.config['JELLYFIN_SERVER_URL']}, timeout = {app.config['JELLYFIN_REQUEST_TIMEOUT']}")

jellyfin = JellyfinClient(app.config['JELLYFIN_SERVER_URL'], app.config['JELLYFIN_REQUEST_TIMEOUT'])
jellyfin_admin_token, jellyfin_admin_id, jellyfin_admin_name, jellyfin_admin_is_admin = jellyfin.login_with_password(
    app.config['JELLYFIN_ADMIN_USER'],
    app.config['JELLYFIN_ADMIN_PASSWORD'], device_id= device_id
)

# SQLAlchemy and Migrate setup
app.logger.info(f"connecting to db: {app.config['JELLYPLIST_DB_HOST']}:{app.config['JELLYPLIST_DB_PORT']}")
db_uri = f'postgresql://{app.config["JELLYPLIST_DB_USER"]}:{app.config["JELLYPLIST_DB_PASSWORD"]}@{app.config["JELLYPLIST_DB_HOST"]}:{app.config['JELLYPLIST_DB_PORT']}/jellyplist'
check_db_connection(db_uri=db_uri,retries=5,delay=2)
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
app.logger.info(f"applying db migrations")
migrate = Migrate(app, db)

# Celery Configuration (Updated)
app.config.update(
    CELERY_BROKER_URL=app.config['REDIS_URL'],     
    result_backend=app.config['REDIS_URL'] 
)

def read_dev_build_file(file_path="/jellyplist/DEV_BUILD"):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            content = file.read().strip()
            return f"-{content}"
    else:
        return ''
app.logger.info(f"initializing celery")
celery = make_celery(app)
socketio = SocketIO(app, message_queue=app.config['REDIS_URL'], async_mode='eventlet')
celery.set_default()

app.logger.info(f'Jellyplist {__version__}{read_dev_build_file()} started')
app.logger.debug(f"Debug logging active")
from app import routes
from app import jellyfin_routes, tasks
if "worker" in sys.argv:
    tasks.release_lock("download_missing_tracks_lock")
    
from app import filters  # Import the filters dictionary

# Register all filters
for name, func in filters.filters.items():
    app.jinja_env.filters[name] = func
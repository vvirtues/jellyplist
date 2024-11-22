from app import db
from sqlalchemy import select

class JellyfinUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    jellyfin_user_id = db.Column(db.String(120), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)  # New property

    # Relationship with Playlist
    playlists = db.relationship('Playlist', secondary='user_playlists', back_populates='users')

    def __repr__(self):
        return f'<JellyfinUser {self.name}:{self.jellyfin_user_id}>'

# Association table between Users and Playlists
user_playlists = db.Table('user_playlists',
    db.Column('user_id', db.Integer, db.ForeignKey('jellyfin_user.id'), primary_key=True),
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id'), primary_key=True),
)

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    spotify_playlist_id = db.Column(db.String(120), unique=True, nullable=False)
    spotify_uri = db.Column(db.String(120), unique=True, nullable=False)
    
    # Relationship with Tracks
    tracks = db.relationship('Track', secondary='playlist_tracks', back_populates='playlists')
    track_count = db.Column(db.Integer())
    tracks_available = db.Column(db.Integer())
    jellyfin_id = db.Column(db.String(120), nullable=True)  
    last_updated = db.Column(db.DateTime )
    last_changed = db.Column(db.DateTime )
    snapshot_id = db.Column(db.String(120), nullable=True)
    # Many-to-Many relationship with JellyfinUser
    users = db.relationship('JellyfinUser', secondary=user_playlists, back_populates='playlists')

    def __repr__(self):
        return f'<Playlist {self.name}:{self.spotify_playlist_id}>'

# Association table between Playlists and Tracks
playlist_tracks = db.Table('playlist_tracks',
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id'), primary_key=True),
    db.Column('track_id', db.Integer, db.ForeignKey('track.id'), primary_key=True),
    db.Column('track_order', db.Integer, nullable=False)  # New field for track order

)

class Track(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    spotify_track_id = db.Column(db.String(120), unique=True, nullable=False)
    spotify_uri = db.Column(db.String(120), unique=True, nullable=False)
    downloaded = db.Column(db.Boolean())
    filesystem_path = db.Column(db.String(), nullable=True)
    jellyfin_id = db.Column(db.String(120), nullable=True)  # Add Jellyfin track ID field
    download_status = db.Column(db.String(2048), nullable=True)

    # Many-to-Many relationship with Playlists
    playlists = db.relationship('Playlist', secondary=playlist_tracks, back_populates='tracks')
    def __repr__(self):
        return f'<Track {self.name}:{self.spotify_track_id}>'

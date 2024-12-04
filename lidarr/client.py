import json
import re
from flask import jsonify
import requests
from typing import List, Optional
from .classes import Album, Artist, QualityProfile, RootFolder
import logging
l = logging.getLogger(__name__)

class LidarrClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url
        self.api_token = api_token
        self.headers = {
            'X-Api-Key': self.api_token
        }

    def _get(self, endpoint: str, params: Optional[dict] = None):
        response = requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()
    def _post(self, endpoint: str, json: dict):
        response = requests.post(f"{self.base_url}{endpoint}", headers=self.headers, json=json)
        response.raise_for_status()
        return response.json()

    def _put(self, endpoint: str, json: dict):
        response = requests.put(f"{self.base_url}{endpoint}", headers=self.headers, json=json)
        response.raise_for_status()
        return response.json()

    def get_album(self, album_id: int) -> Album:
        l.debug(f"Getting album {album_id}")
        data = self._get(f"/api/v1/album/{album_id}")
        return Album(**data)

    def get_artist(self, artist_id: int) -> Artist:
        l.debug(f"Getting artist {artist_id}")
        data = self._get(f"/api/v1/artist/{artist_id}")
        return Artist(**data)

    def search(self, term: str) -> List[object]:
        l.debug(f"Searching for {term}")
        data = self._get("/api/v1/search", params={"term": term})
        results = []
        for item in data:
            if 'artist' in item:
                results.append(Artist(**item['artist']))
            elif 'album' in item:
                results.append(Album(**item['album']))
        return results
    # A method which takes a List[object] end external URL as parameter, and returns the object from the List[object] which has the same external URL as the parameter.
    def get_object_by_external_url(self, objects: List[object], external_url: str) -> object:
        l.debug(f"Getting object by external URL {external_url}")
        # We need to check whether the external_url matches intl-[a-zA-Z]{2}\/ it has to be replaced by an empty string
        external_url = re.sub(r"intl-[a-zA-Z]{2}\/", "", external_url)  
        for obj in objects:
            # object can either be an Album or an Artist, so it can be verified and casted
            if isinstance(obj, Album):
                for link in obj.links:
                    if link['url'] == external_url:
                        return obj
            elif isinstance(obj, Artist):
                for link in obj.links:
                    if link['url'] == external_url:
                        return obj
                
        return None
    # A method to get all Albums from List[object] where the name equals the parameter name
    def get_albums_by_name(self, objects: List[object], name: str) -> List[Album]:
        l.debug(f"Getting albums by name {name}")
        albums = []
        for obj in objects:
            if isinstance(obj, Album) and obj.title == name:
                artist = Artist(**obj.artist)
                obj.artist = artist
                albums.append(obj)
        return albums
            
    # a method to get all artists from List[object] where the name equals the parameter name 
    def get_artists_by_name(self, objects: List[object], name: str) -> List[Artist]:
        l.debug(f"Getting artists by name {name}")
        artists = []
        for obj in objects:
            if isinstance(obj, Artist) and obj.artistName == name:
                artists.append(obj)
        return artists
    
    def create_album(self, album: Album) -> Album:
        l.debug(f"Creating album {album.title}")
        json_artist = album.artist.__dict__
        album.artist = json_artist
        data = self._post("/api/v1/album", json=album.__dict__)
        return Album(**data)

    def update_album(self, album_id: int, album: Album) -> Album:
        l.debug(f"Updating album {album_id}")
        json_artist = album.artist.__dict__
        album.artist = json_artist
        data = self._put(f"/api/v1/album/{album_id}", json=album.__dict__)
        return Album(**data)

    def create_artist(self, artist: Artist) -> Artist:
        l.debug(f"Creating artist {artist.artistName}")
        data = self._post("/api/v1/artist", json=artist.__dict__)
        return Artist(**data)

    def update_artist(self, artist_id: int, artist: Artist) -> Artist:
        l.debug(f"Updating artist {artist_id}")
        data = self._put(f"/api/v1/artist/{artist_id}", json=artist.__dict__)
        return Artist(**data)
    
    # shorthand method to set artist to monitored
    def monitor_artist(self, artist: Artist):
        artist.monitored = True
        l.debug(f"Monitoring artist {artist.artistName}")
        if artist.id == 0:
            artist = self.create_artist(artist)
        else:
            self.update_artist(artist.id, artist)
    # shorthand method to set album to monitored
    def monitor_album(self, album: Album):
        album.monitored = True
        
        l.debug(f"Monitoring album {album.title}")
        if album.id == 0:
            album = self.create_album(album)
        else:
            self.update_album(album.id, album)
            
    # a method to query /api/v1/rootfolder and return a List[RootFolder]
    def get_root_folders(self) -> List[RootFolder]:
        l.debug("Getting root folders")
        data = self._get("/api/v1/rootfolder")
        return [RootFolder(**folder) for folder in data]
    
    # a method to query /api/v1/qualityprofile and return a List[QualityProfile]
    def get_quality_profiles(self) -> List[QualityProfile]:
        l.debug("Getting quality profiles")
        data = self._get("/api/v1/qualityprofile")
        return [QualityProfile(**profile) for profile in data]
    
        
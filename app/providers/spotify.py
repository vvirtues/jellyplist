import os
from app.providers.base import Album, MusicProviderClient,Playlist,Track,ExternalUrl,Category
import requests

import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from typing import List, Dict, Optional
from http.cookiejar import MozillaCookieJar

class SpotifyClient(MusicProviderClient):
    """
    Spotify implementation of the MusicProviderClient.
    """

    def __init__(self, cookie_file: Optional[str] = None):
        self.base_url = "https://api-partner.spotify.com"
        self.session_data = None
        self.config_data = None
        self.client_token = None
        self.cookies = None
        if cookie_file:
            self._load_cookies(cookie_file)
            
    def _load_cookies(self, cookie_file: str) -> None:
        """
        Load cookies from a file.

        :param cookie_file: Path to the cookie file.
        """
        if not os.path.exists(cookie_file):
            raise FileNotFoundError(f"Cookie file not found: {cookie_file}")

        cookie_jar = MozillaCookieJar(cookie_file)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        self.cookies = requests.utils.dict_from_cookiejar(cookie_jar)

    def authenticate(self, credentials: dict) -> None:
        """
        Authenticate with Spotify by fetching session data and client token.
        """
        def fetch_session_data():
            url = f'https://open.spotify.com/'
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            }
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            session_script = soup.find('script', {'id': 'session'})
            config_script = soup.find('script', {'id': 'config'})
            if session_script and config_script:
                return json.loads(session_script.string), json.loads(config_script.string)
            else:
                raise ValueError("Failed to fetch session or config data.")

        
        self.session_data, self.config_data = fetch_session_data()

        def fetch_client_token():
            url = f'https://clienttoken.spotify.com/v1/clienttoken'
            headers = {
                'accept': 'application/json',
                'content-type': 'application/json',
                'origin': 'https://open.spotify.com',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            }
            payload = {
                "client_data": {
                    "client_version": "1.2.52.404.gcb99a997",
                    "client_id": self.session_data.get("clientId", ""),
                    "js_sdk_data": {
                        "device_brand": "unknown",
                        "device_model": "unknown",
                        "os": "windows",
                        "os_version": "NT 10.0",
                        "device_id": self.config_data.get("correlationId", ""),
                        "device_type": "computer"
                    }
                }
            }
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json().get("granted_token", "")

        self.client_token = fetch_client_token()

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """
        Helper method to make authenticated requests to Spotify APIs.
        """
        headers = {
            'accept': 'application/json',
            'app-platform': 'WebPlayer',
            'authorization': f'Bearer {self.session_data.get("accessToken", "")}',
            'client-token': self.client_token.get('token',''),
        }
        response = requests.get(f"{self.base_url}/{endpoint}", headers=headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_playlist(self, playlist_id: str) -> Playlist:
        """
        Fetch a playlist by ID with all tracks.
        """
        limit = 50
        offset = 0
        all_items = []

        while True:
            query_parameters = {
                "operationName": "fetchPlaylist",
                "variables": json.dumps({
                    "uri": f"spotify:playlist:{playlist_id}",
                    "offset": offset,
                    "limit": limit
                }),
                "extensions": json.dumps({
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": "19ff1327c29e99c208c86d7a9d8f1929cfdf3d3202a0ff4253c821f1901aa94d"
                    }
                })
            }
            encoded_query = urlencode(query_parameters)
            data = self._make_request(f"pathfinder/v1/query?{encoded_query}")
            playlist_data = data.get('data', {}).get('playlistV2', {})
            content = playlist_data.get('content', {})
            items = content.get('items', [])
            all_items.extend(items)

            if len(all_items) >= content.get('totalCount', 0):
                break

            offset += limit

        tracks = [
            Track(
                id=item["itemV2"]["data"]["uri"].split(":")[-1],
                name=item["itemV2"]["data"]["name"],
                uri=item["itemV2"]["data"]["uri"],
                duration_ms=item["itemV2"]["data"]["trackDuration"]["totalMilliseconds"],
                explicit=False,  # Default as Spotify API doesn't provide explicit info here
                album=item["itemV2"]["data"]["albumOfTrack"]["name"],
                artists=[
                    artist["profile"]["name"]
                    for artist in item["itemV2"]["data"]["albumOfTrack"]["artists"]["items"]
                ]
            )
            for item in all_items
        ]
        return Playlist(
            id=playlist_id,
            name=playlist_data.get("name", ""),
            description=playlist_data.get("description", ""),
            uri=playlist_data.get("uri", ""),
            tracks=tracks,
        )

    def search_tracks(self, query: str, limit: int = 10) -> List[Track]:
        """
        Searches for tracks on Spotify.
        :param query: Search query.
        :param limit: Maximum number of results.
        :return: A list of Track objects.
        """
        print(f"search_tracks: Placeholder for search with query '{query}' and limit {limit}.")
        return []

    def get_track(self, track_id: str) -> Track:
        """
        Fetches details for a specific track.
        :param track_id: The ID of the track.
        :return: A Track object.
        """
        print(f"get_track: Placeholder for track with ID {track_id}.")
        return Track(id=track_id, name="", uri="", duration_ms=0, explicit=False, album=Album(), artists=[], external_urls= ExternalUrl())

    def get_featured_playlists(self, limit: int = 10) -> List[Playlist]:
        """
        Fetches featured playlists.
        :param limit: Maximum number of results.
        :return: A list of Playlist objects.
        """
        print(f"get_featured_playlists: Placeholder for featured playlists with limit {limit}.")
        return []

    def get_playlists_by_category(self, category_id: str, limit: int = 10) -> List[Playlist]:
        """
        Fetches playlists for a specific category.
        :param category_id: The ID of the category.
        :param limit: Maximum number of results.
        :return: A list of Playlist objects.
        """
        print(f"get_playlists_by_category: Placeholder for playlists in category {category_id}.")
        return []

    def get_categories(self, limit: int = 10) -> List[Category]:
        """
        Fetches categories from Spotify.
        :param limit: Maximum number of results.
        :return: A list of Category objects.
        """
        print(f"get_categories: Placeholder for categories with limit {limit}.")
        return []
import time
from bs4 import BeautifulSoup
import deezer
import deezer.resources
import deezer.exceptions
import json 
import requests
from typing import List, Optional, Dict
import logging
from deezer import Client

from app.providers.base import (
    MusicProviderClient,
    AccountAttributes,
    Album,
    Artist,
    BrowseCard,
    BrowseSection,
    Image,
    Owner,
    Playlist,
    PlaylistTrack,
    Profile,
    Track,
    ExternalUrl,
    Category,
)

l = logging.getLogger(__name__)

class DeezerClient(MusicProviderClient):
    """
    Deezer implementation of the MusicProviderClient.
    An abstraction layer of deezer-python 
    https://github.com/browniebroke/deezer-python library to work with Jellyplist.
    """

    @property
    def _identifier(self) -> str:
        return "Deezer"
    
    

    def __init__(self, access_token: Optional[str] = None):
        """
        Initialize the Deezer client.
        :param access_token: Optional access token for authentication.
        """
        self._client = deezer.Client(access_token=access_token)
        
    #region Helper methods for parsing Deezer API responses    
    def _parse_track(self, track: deezer.resources.Track) -> Track:
        """
        Parse a track object.
        :param track: The track object from the Deezer API.
        :return: A Track object.
        """
        
        l.debug(f"Track: {track}")
        retrycount= 0
        max_retries = 3
        wait = .8
        while True:
            try:
                artists = [self._parse_artist(track.artist)]
                if hasattr(track, 'contributors'):
                    artists = [self._parse_artist(artist) for artist in track.contributors]
                return Track(
                    id=str(track.id),
                    name=track.title,
                    uri=f"deezer:track:{track.id}",
                    duration_ms=track.duration * 1000,
                    explicit=track.explicit_lyrics,
                    album=self._parse_album(track.album),
                    artists=artists,
                    external_urls=[],
                )
            except deezer.exceptions.DeezerErrorResponse as e:
                if e.json_data['error']['code'] == 4:
                    l.warning(f"Quota limit exceeded. Waiting for {wait} seconds before retrying...")
                    retrycount += 1
                    if retrycount >= max_retries:
                        l.error("Maximum retries reached. Aborting.")
                        raise
                    time.sleep(wait)
                else:
                    raise
    def _parse_artist(self, artist: deezer.resources.Artist) -> Artist:
        """
        Parse an artist object.
        :param artist: The artist object from the Deezer API.
        :return: An Artist object.
        """
        return Artist(
            id=str(artist.id),
            name=artist.name,
            uri=f"deezer:artist:{artist.id}",
            external_urls=[],
        )
        
    def _parse_album(self, album: deezer.resources.Album) -> Album:
        """
        Parse an album object.
        :param album: The album object from the Deezer API.
        :return: An Album object.
        """
        #artists = [self._parse_artist(artist) for artist in album.contributors]
        artists = []
        images = [Image(url=album.cover_xl, height=None, width=None)]
        return Album(
            id=str(album.id),
            name=album.title,
            uri=f"deezer:album:{album.id}",
            external_urls=[],
            artists=artists,
            images=images
        )
    def _parse_playlist(self, playlist: deezer.resources.Playlist) -> Playlist:
        """
        Parse a playlist object.
        :param playlist: The playlist object from the Deezer API.
        :return: A Playlist object.
        """
        images = [Image(url=playlist.picture_medium, height=None, width=None)]
        tracks = []
        tracks = [PlaylistTrack(is_local=False, track=self._parse_track(playlist_track), added_at='', added_by='') for playlist_track in playlist.get_tracks()]
        
            
        return Playlist(
            id=str(playlist.id),
            name=playlist.title,
            uri=f"deezer:playlist:{playlist.id}",
            external_urls=[ExternalUrl(url=playlist.link)],
            description=playlist.description,
            public=playlist.public,
            collaborative=playlist.collaborative,
            followers=playlist.fans,
            images=images,
            owner=Owner(
                id=str(playlist.creator.id),
                name=playlist.creator.name,
                uri=f"deezer:user:{playlist.creator.id}",
                external_urls=[ExternalUrl(url=playlist.creator.link)]
            ),
            tracks=tracks
        )
        
    #endregion
    def authenticate(self, credentials: Optional[dict] = None) -> None:
        """
        Authenticate with Deezer using an access token.
        :param credentials: Optional dictionary containing 'access_token'.
        """
        l.info("Authentication is handled by deezer-python.")
        pass

    def extract_playlist_id(self, uri: str) -> str:
        """
        Extract the playlist ID from a Deezer playlist URL or URI.
        :param uri: The playlist URL or URI.
        :return: The playlist ID.
        """
        # TODO: Implement this method
        return ''

    def get_playlist(self, playlist_id: str) -> Playlist:
        """
        Fetch a playlist by its ID.
        :param playlist_id: The ID of the playlist to fetch.
        :return: A Playlist object.
        """
        data = self._client.get_playlist(int(playlist_id))
        return self._parse_playlist(data)

    def search_playlist(self, query: str, limit: int = 50) -> List[Playlist]:
        """
        Search for playlists matching a query.
        :param query: The search query.
        :param limit: Maximum number of results to return.
        :return: A list of Playlist objects.
        """
        playlists = []
        search_results = self._client.search_playlists(query, strict=None, ordering=None)
        for item in search_results:
            images = [Image(url=item.picture_xl, height=None, width=None)]
            tracks = [PlaylistTrack(is_local=False, track=self._parse_track(playlist_track), added_at='', added_by='') for playlist_track in item.tracks]
            playlist = Playlist(
                id=str(item.id),
                name=item.title,
                uri=f"deezer:playlist:{item.id}",
                external_urls=[ExternalUrl(url=item.link)],
                description=item.description,
                public=item.public,
                collaborative=item.collaborative,
                followers=item.fans,
                images=images,
                owner=Owner(
                    id=str(item.creator.id),
                    name=item.create.name,
                    uri=f"deezer:user:{item.creator.id}",
                    external_urls=[ExternalUrl(url=item.creator.link)]
                ),
                tracks=tracks
            )
            playlists.append(playlist)
        return playlists
    
        
    def get_track(self, track_id: str) -> Track:
        """
        Fetch a track by its ID.
        :param track_id: The ID of the track to fetch.
        :return: A Track object.
        """
        track = self._client.get_track(int(track_id))
        return self._parse_track(track)

    
    def browse(self, **kwargs) -> List[BrowseSection]:
        """
        Browse featured content.
        :param kwargs: Additional parameters.
        :return: A list of BrowseSection objects.
        """
        # Deezer does not have a direct equivalent, but we can fetch charts
        url = 'https://www.deezer.com/de/channels/explore/explore-tab'
        headers = {
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
            'sec-ch-ua': '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0'
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        dzr_app_div = soup.find('div', id='dzr-app')
        script_tag = dzr_app_div.find('script')

        script_content = script_tag.string.strip()
        json_content = script_content.replace('window.__DZR_APP_STATE__ = ', '', 1)
        data = json.loads(json_content)

        sections = []
        for section in data['sections']:
            browse_section = None
            if 'module_type=channel' in section['section_id']:
                cards = []
                for item in section['items']:
                    if item['type'] == 'channel':
                        image_url = f"https://cdn-images.dzcdn.net/images/{item['image_linked_item']['type']}/{item['image_linked_item']['md5']}/256x256-000000-80-0-0.jpg"
                        card = BrowseCard(
                            title=item['title'],
                            uri=f"deezer:channel:{item['data']['slug']}",
                            artwork=[Image(url=image_url, height=None, width=None)],
                            background_color=item['data']['background_color']
                        )
                        cards.append(card)
                browse_section = BrowseSection(
                    title=section['title'],
                    uri=f"deezer:section:{section['group_id']}",
                    items=cards
                )
            if browse_section:
                sections.append(browse_section)
        return sections

    def browse_page(self, uri: str) -> List[Playlist]:
        """
        Fetch playlists for a given browse page.
        :param uri: The uri to query.
        :return: A list of Playlist objects.
        """
        # Deezer does not have a direct equivalent, but we can fetch charts
        playlists = []
        slug = uri.split(':')[-1]
        url = f'https://www.deezer.com/de/channels/{slug}'
        headers = {
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
            'sec-ch-ua': '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0'
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        dzr_app_div = soup.find('div', id='dzr-app')
        script_tag = dzr_app_div.find('script')

        script_content = script_tag.string.strip()
        json_content = script_content.replace('window.__DZR_APP_STATE__ = ', '', 1)
        data = json.loads(json_content)
        for section in data['sections']:
            for item in section['items']:
                if item['type'] == 'playlist':
                    #playlist = self.get_playlist(item['data']['slug'])
                    image_url = f"https://cdn-images.dzcdn.net/images/{item['type']}/{item['data']['PLAYLIST_PICTURE']}/256x256-000000-80-0-0.jpg"
                    playlist = Playlist(
                        id=str(item['id']),
                        name=item['title'],
                        uri=f"deezer:playlist:{item['id']}",
                        external_urls=[ExternalUrl(url=f"https://www.deezer.com/playlist/{item['target']}")],
                        description=item.get('catption',''),
                        public=True, # TODO: Check if this is correct
                        collaborative=False, # TODO: Check if this is correct
                        followers=item['data']['NB_FAN'],
                        images=[Image(url=image_url, height=None, width=None)],
                        owner=Owner(
                            id=item['data'].get('PARENT_USERNAME',''),
                            name=item['data'].get('PARENT_USERNAME',''),
                            uri=f"deezer:user:{item['data'].get('PARENT_USERNAME','')}",
                            external_urls=[ExternalUrl(url='')]
                        )
                    )
                    playlists.append(playlist)
        return playlists
    
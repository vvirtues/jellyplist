from dataclasses import dataclass, field
from typing import List, Optional
from abc import ABC, abstractmethod



@dataclass
class ExternalUrl:
    url: str
    
@dataclass 
class ItemBase:
    id: str
    name: str
    uri: str
    external_urls: Optional[List[ExternalUrl]]
    
@dataclass
class Profile:
    avatar: Optional[str]  # Avatar URL or None
    avatar_background_color: Optional[int]
    name: str
    uri: str
    username: str
    
@dataclass
class AccountAttributes:
    catalogue: str
    dsa_mode_available: bool
    dsa_mode_enabled: bool
    multi_user_plan_current_size: Optional[int]
    multi_user_plan_member_type: Optional[str]
    on_demand: bool
    opt_in_trial_premium_only_market: bool
    country: str
    product: str

@dataclass
class Image:
    url: str
    height: Optional[int]
    width: Optional[int]

@dataclass
class Artist(ItemBase):
    pass

@dataclass
class Album(ItemBase):
    artists: List[Artist]
    images: List[Image]

@dataclass
class Track(ItemBase):
    duration_ms: int
    explicit: Optional[bool]
    album: Optional[Album]
    artists: List[Artist]

@dataclass
class PlaylistTrack:
    added_at: Optional[str]
    added_by: Optional[str]
    is_local: bool
    track: Track

@dataclass
class Owner(ItemBase):
    pass

@dataclass #tbc
class Category(ItemBase):
    pass
    
@dataclass
class Playlist(ItemBase):
    
    description: Optional[str]
    public: Optional[bool]
    collaborative: Optional[bool]
    followers: Optional[int]
    images: Optional[List[Image]]
    owner: Optional[Owner]
    tracks: List[PlaylistTrack] = field(default_factory=list)

# Abstract base class for music providers
class MusicProviderClient(ABC):
    """
    Abstract base class defining the interface for music provider clients.
    """

    @abstractmethod
    def authenticate(self, credentials: dict) -> None:
        """
        Authenticates the client with the provider using the provided credentials.
        :param credentials: A dictionary containing credentials (e.g., API keys, tokens).
        """
        pass

    @abstractmethod
    def get_playlist(self, playlist_id: str) -> Playlist:
        """
        Fetches a playlist by its ID.
        :param playlist_id: The ID of the playlist to fetch.
        :return: A Playlist object.
        """
        pass

    @abstractmethod
    def search_tracks(self, query: str, limit: int = 50) -> List[Track]:
        """
        Searches for tracks based on a query string.
        :param query: The search query.
        :param limit: Maximum number of results to return.
        :return: A list of Track objects.
        """
        pass

    @abstractmethod
    def get_track(self, track_id: str) -> Track:
        """
        Fetches details for a specific track.
        :param track_id: The ID of the track to fetch.
        :return: A Track object.
        """
        pass
    @abstractmethod
    def get_featured_playlists(self, limit: int = 50) -> List[Playlist]:
        """
        Fetches a list of featured playlists.
        :param limit: Maximum number of featured playlists to return.
        :return: A list of Playlist objects.
        """
        pass

    @abstractmethod
    def get_playlists_by_category(self, category_id: str, limit: int = 50) -> List[Playlist]:
        """
        Fetches playlists belonging to a specific category.
        :param category_id: The ID of the category.
        :param limit: Maximum number of playlists to return.
        :return: A list of Playlist objects.
        """
        pass

    @abstractmethod
    def get_categories(self, limit: int = 50) -> List[Category]:
        """
        Fetches a list of available categories.
        :param limit: Maximum number of categories to return.
        :return: A list of categories, where each category is a dictionary with 'id' and 'name'.
        """
        pass
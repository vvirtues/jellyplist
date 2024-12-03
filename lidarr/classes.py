from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Image:
    url: str
    coverType: str
    extension: str
    remoteUrl: str

@dataclass
class Link:
    url: str
    name: str

@dataclass
class Ratings:
    votes: int
    value: float

@dataclass
class AddOptions:
    monitor: str
    albumsToMonitor: List[str]
    monitored: bool
    searchForMissingAlbums: bool

@dataclass
class Statistics:
    albumCount: int
    trackFileCount: int
    trackCount: int
    totalTrackCount: int
    sizeOnDisk: int
    percentOfTracks: float

@dataclass
class Member:
    name: str
    instrument: str
    images: List[Image]

@dataclass
class Artist:
    mbId: Optional[str] = None
    tadbId: Optional[int] = None
    discogsId: Optional[int] = None
    allMusicId: Optional[str] = None
    overview: str = ""
    artistType: str = ""
    disambiguation: str = ""
    links: List[Link] = field(default_factory=list)
    nextAlbum: str = ""
    lastAlbum: str = ""
    images: List[Image] = field(default_factory=list)
    members: List[Member] = field(default_factory=list)
    remotePoster: str = ""
    path: str = ""
    qualityProfileId: int = 0
    metadataProfileId: int = 0
    monitored: bool = False
    monitorNewItems: str = ""
    rootFolderPath: Optional[str] = None
    folder: str = ""
    genres: List[str] = field(default_factory=list)
    cleanName: str = ""
    sortName: str = ""
    tags: List[int] = field(default_factory=list)
    added: str = ""
    addOptions: Optional[AddOptions] = None
    ratings: Optional[Ratings] = None
    statistics: Optional[Statistics] = None
    status : str = ""
    ended : bool = False
    artistName : str = ""
    foreignArtistId : str = ""
    id : int = 0
    

@dataclass
class Media:
    mediumNumber: int
    mediumName: str
    mediumFormat: str

@dataclass
class Release:
    id: int
    albumId: int
    foreignReleaseId: str
    title: str
    status: str
    duration: int
    trackCount: int
    media: List[Media]
    mediumCount: int
    disambiguation: str
    country: List[str]
    label: List[str]
    format: str
    monitored: bool

@dataclass
class Album:
    id: int = 0
    title: str = ""
    disambiguation: str = ""
    overview: str = ""
    artistId: int = 0
    foreignAlbumId: str = ""
    monitored: bool = False
    anyReleaseOk: bool = False
    profileId: int = 0
    duration: int = 0
    albumType: str = ""
    secondaryTypes: List[str] = field(default_factory=list)
    mediumCount: int = 0
    ratings: Ratings = None
    releaseDate: str = ""
    releases: List[Release] = field(default_factory=list)
    genres: List[str] = field(default_factory=list)
    media: List[Media] = field(default_factory=list)
    artist: Artist = field(default_factory=Artist)
    images: List[Image] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    lastSearchTime: str = ""
    statistics: Statistics = None
    addOptions: Optional[dict] = field(default_factory=dict)
    remoteCover: str = ""

@dataclass
class RootFolder:
    id: int = 0
    name: str = ""
    path: str = ""
    defaultMetadataProfileId: int = 0
    defaultQualityProfileId: int = 0
    defaultMonitorOption: str = ""
    defaultNewItemMonitorOption: str = ""
    defaultTags: List[int] = field(default_factory=list)
    accessible: bool = False
    freeSpace: int = 0
    totalSpace: int = 0
    
@dataclass
class Quality:
    id: int = 0
    name: str = ""

@dataclass
class Item:
    id: int = 0
    name: str = ""
    quality: Quality = field(default_factory=Quality)
    items: List[str] = field(default_factory=list)
    allowed: bool = False

@dataclass
class FormatItem:
    id: int = 0
    format: int = 0
    name: str = ""
    score: int = 0

@dataclass
class QualityProfile:
    id: int = 0
    name: str = ""
    upgradeAllowed: bool = False
    cutoff: int = 0
    items: List[Item] = field(default_factory=list)
    minFormatScore: int = 0
    cutoffFormatScore: int = 0
    formatItems: List[FormatItem] = field(default_factory=list)
from ast import List


class PlaylistMetadata:
    def __init__(self, playlist_data=None):
        # Initialize with existing data if available, otherwise use default values
        self.Id = playlist_data.get("Id") if playlist_data else None
        self.Name = playlist_data.get("Name", "") if playlist_data else None
        self.OriginalTitle = playlist_data.get("OriginalTitle", "") if playlist_data else None
        self.ForcedSortName = playlist_data.get("ForcedSortName", "") if playlist_data else None
        self.CommunityRating = playlist_data.get("CommunityRating", "") if playlist_data else None
        self.CriticRating = playlist_data.get("CriticRating", "") if playlist_data else None
        self.IndexNumber = playlist_data.get("IndexNumber", None) if playlist_data else None
        self.AirsBeforeSeasonNumber = playlist_data.get("AirsBeforeSeasonNumber", "") if playlist_data else None
        self.AirsAfterSeasonNumber = playlist_data.get("AirsAfterSeasonNumber", "") if playlist_data else None
        self.AirsBeforeEpisodeNumber = playlist_data.get("AirsBeforeEpisodeNumber", "") if playlist_data else None
        self.ParentIndexNumber = playlist_data.get("ParentIndexNumber", None) if playlist_data else None
        self.DisplayOrder = playlist_data.get("DisplayOrder", "") if playlist_data else None
        self.Album = playlist_data.get("Album", "") if playlist_data else None
        self.AlbumArtists = playlist_data.get("AlbumArtists", []) if playlist_data else []
        self.ArtistItems = playlist_data.get("ArtistItems", []) if playlist_data else []
        self.Overview = playlist_data.get("Overview", "") if playlist_data else None
        self.Status = playlist_data.get("Status", "") if playlist_data else None
        self.AirDays = playlist_data.get("AirDays", []) if playlist_data else []
        self.AirTime = playlist_data.get("AirTime", "") if playlist_data else None
        self.Genres = playlist_data.get("Genres", []) if playlist_data else []
        self.Tags = playlist_data.get("Tags", []) if playlist_data else list[str]
        self.Studios = playlist_data.get("Studios", []) if playlist_data else []
        self.PremiereDate = playlist_data.get("PremiereDate", None) if playlist_data else None
        self.DateCreated = playlist_data.get("DateCreated", None) if playlist_data else None
        self.EndDate = playlist_data.get("EndDate", None) if playlist_data else None
        self.ProductionYear = playlist_data.get("ProductionYear", "") if playlist_data else None
        self.Height = playlist_data.get("Height", "") if playlist_data else None
        self.AspectRatio = playlist_data.get("AspectRatio", "") if playlist_data else None
        self.Video3DFormat = playlist_data.get("Video3DFormat", "") if playlist_data else None
        self.OfficialRating = playlist_data.get("OfficialRating", "") if playlist_data else None
        self.CustomRating = playlist_data.get("CustomRating", "") if playlist_data else None
        self.People = playlist_data.get("People", []) if playlist_data else []
        self.LockData = playlist_data.get("LockData", False) if playlist_data else False
        self.LockedFields = playlist_data.get("LockedFields", []) if playlist_data else []
        self.ProviderIds = playlist_data.get("ProviderIds", {}) if playlist_data else {}
        self.PreferredMetadataLanguage = playlist_data.get("PreferredMetadataLanguage", "") if playlist_data else None
        self.PreferredMetadataCountryCode = playlist_data.get("PreferredMetadataCountryCode", "") if playlist_data else None
        self.Taglines = playlist_data.get("Taglines", []) if playlist_data else []

    def to_dict(self):
        """
        Converts the PlaylistMetadata object to a dictionary.
        """
        return {
            "Id": self.Id,
            "Name": self.Name,
            "OriginalTitle": self.OriginalTitle,
            "ForcedSortName": self.ForcedSortName,
            "CommunityRating": self.CommunityRating,
            "CriticRating": self.CriticRating,
            "IndexNumber": self.IndexNumber,
            "AirsBeforeSeasonNumber": self.AirsBeforeSeasonNumber,
            "AirsAfterSeasonNumber": self.AirsAfterSeasonNumber,
            "AirsBeforeEpisodeNumber": self.AirsBeforeEpisodeNumber,
            "ParentIndexNumber": self.ParentIndexNumber,
            "DisplayOrder": self.DisplayOrder,
            "Album": self.Album,
            "AlbumArtists": self.AlbumArtists,
            "ArtistItems": self.ArtistItems,
            "Overview": self.Overview,
            "Status": self.Status,
            "AirDays": self.AirDays,
            "AirTime": self.AirTime,
            "Genres": self.Genres,
            "Tags": self.Tags,
            "Studios": self.Studios,
            "PremiereDate": self.PremiereDate,
            "DateCreated": self.DateCreated,
            "EndDate": self.EndDate,
            "ProductionYear": self.ProductionYear,
            "Height": self.Height,
            "AspectRatio": self.AspectRatio,
            "Video3DFormat": self.Video3DFormat,
            "OfficialRating": self.OfficialRating,
            "CustomRating": self.CustomRating,
            "People": self.People,
            "LockData": self.LockData,
            "LockedFields": self.LockedFields,
            "ProviderIds": self.ProviderIds,
            "PreferredMetadataLanguage": self.PreferredMetadataLanguage,
            "PreferredMetadataCountryCode": self.PreferredMetadataCountryCode,
            "Taglines": self.Taglines,
        }

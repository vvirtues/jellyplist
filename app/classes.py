from dataclasses import dataclass
from datetime import datetime
import subprocess
import json
from flask import current_app as app  # Adjust this based on your app's structure
from typing import List, Optional


class AudioProfile:
    def __init__(self, path: str, bitrate: int = 0, sample_rate: int = 0, channels: int = 0) -> None:
        """
        Initialize an AudioProfile instance.

        Args:
            path (str): The file path of the audio file.
            bitrate (int): The audio bitrate in kbps. Default is 0.
            sample_rate (int): The sample rate in Hz. Default is 0.
            channels (int): The number of audio channels. Default is 0.
        """
        self.path: str = path
        self.bitrate: int = bitrate  # in kbps
        self.sample_rate: int = sample_rate  # in Hz
        self.channels: int = channels

    @staticmethod
    def analyze_audio_quality_with_ffprobe(filepath: str) -> Optional['AudioProfile']:
        """
        Static method to analyze audio quality using ffprobe and return an AudioProfile instance.

        Args:
            filepath (str): Path to the audio file to analyze.

        Returns:
            Optional[AudioProfile]: An instance of AudioProfile if analysis is successful, None otherwise.
        """
        try:
            # ffprobe command to extract bitrate, sample rate, and channel count
            cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'a:0',
                '-show_entries', 'stream=bit_rate,sample_rate,channels',
                '-show_format',
                '-of', 'json', filepath
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                app.logger.error(f"ffprobe error for file {filepath}: {result.stderr}")
                return None

            # Parse ffprobe output
            data = json.loads(result.stdout)
            stream = data.get('streams', [{}])[0]
            bitrate: int = int(stream.get('bit_rate', 0)) // 1000  # Convert to kbps
            if bitrate == 0:  # Fallback if no bit_rate in stream
                bitrate = int(data.get('format').get('bit_rate', 0)) // 1000
            sample_rate: int = int(stream.get('sample_rate', 0))  # Hz
            channels: int = int(stream.get('channels', 0))

            # Create an AudioProfile instance
            return AudioProfile(filepath, bitrate, sample_rate, channels)
        except Exception as e:
            app.logger.error(f"Error analyzing audio quality with ffprobe: {str(e)}")
            return None

    def compute_quality_score(self) -> int:
        """
        Compute a quality score based on bitrate, sample rate, and channels.

        Returns:
            int: The computed quality score.
        """
        return self.bitrate + (self.sample_rate // 1000) + (self.channels * 10)

    def __repr__(self) -> str:
        """
        Representation of the AudioProfile instance.

        Returns:
            str: A string representation of the AudioProfile instance.
        """
        return (f"AudioProfile(path='{self.path}', bitrate={self.bitrate} kbps, "
                f"sample_rate={self.sample_rate} Hz, channels={self.channels})")


@dataclass
class CombinedTrackData():
    # Combines a track from a provider with a track from the db
    title: str
    artist: List[str]
    url: List[str]
    duration: str
    downloaded: bool
    filesystem_path: Optional[str]
    jellyfin_id: Optional[str]
    provider_id: str
    provider_track_id: str
    duration_ms: int
    download_status: Optional[str]
    provider: str
    
@dataclass
class CombinedPlaylistData():
    name: str
    description: Optional[str]
    image: str
    url: str
    id: str
    jellyfin_id: Optional[str]
    can_add: bool
    can_remove: bool
    last_updated: Optional[datetime]
    last_changed: Optional[datetime]
    tracks_available: int
    track_count: int
    tracks_linked: int
    percent_available: float
    status: str
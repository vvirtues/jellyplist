from flask import g
from providers.base import MusicProviderClient

g: "Global"

class Global:
    music_provider: MusicProviderClient
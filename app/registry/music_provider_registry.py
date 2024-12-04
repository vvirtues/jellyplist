from app.providers.base import MusicProviderClient


class MusicProviderRegistry:
    """
    Registry to manage and retrieve music provider clients.
    """
    _providers = {}

    @classmethod
    def register_provider(cls, provider: MusicProviderClient):
        """
        Registers a music provider client instance.
        :param provider: An instance of a MusicProviderClient subclass.
        """
        cls._providers[provider._identifier] = provider

    @classmethod
    def get_provider(cls, identifier: str) -> MusicProviderClient:
        """
        Retrieves a registered music provider client by its identifier.
        :param identifier: The unique identifier for the provider.
        :return: An instance of MusicProviderClient.
        """
        if identifier not in cls._providers:
            raise ValueError(f"No provider found with identifier '{identifier}'.")
        return cls._providers[identifier]

    @classmethod
    def list_providers(cls) -> list:
        """
        Lists all registered providers.
        :return: A list of registered provider identifiers.
        """
        return list(cls._providers.keys())

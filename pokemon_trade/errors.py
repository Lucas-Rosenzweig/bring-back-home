"""Stable errors exposed by the trade library."""


class TradeError(Exception):
    """Base class for expected, user-actionable trade failures."""


class UnsupportedGameError(TradeError):
    """The LDN metadata does not select a supported game plugin."""


class AmbiguousGameError(UnsupportedGameError):
    """More than one game plugin claims the same LDN session."""


class InvalidArtifactError(TradeError):
    """An offered or received Pokémon artifact is malformed."""


class MalformedDatagramError(TradeError):
    """A game plugin received a datagram that cannot be decoded safely."""


class CryptoError(TradeError):
    """A protocol authentication or decryption operation failed."""


class ProtocolStateError(TradeError):
    """A peer message is invalid for the current protocol state."""


class TradeTimeoutError(TradeError):
    """A bounded protocol wait elapsed without the required progress."""


class PeerDisconnectedError(TradeError):
    """The LDN peer disconnected before the trade completed."""


class TradeCancelledError(TradeError):
    """The caller cancelled the trade."""

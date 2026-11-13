"""What can go wrong when resolving a market link."""


class NotAVenueLink(ValueError):
    """The text is not a Kalshi or Polymarket market link."""


class MarketNotFound(LookupError):
    """The venue has no open market there."""


class VenueError(Exception):
    """The venue failed or answered in a shape we do not understand."""

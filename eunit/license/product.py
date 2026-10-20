"""Product identity: the only place to change when renaming or selling the product."""
from .. import __version__

PRODUCT_NAME = "e2Unit"
PRODUCT_VERSION = __version__

# Lemon Squeezy store "esquaresoft" (Settings > Stores for the id), shared with eScope
STORE_ID = 496238
# e2Unit product of the store (product page for the id and the buy link).
# None until the product exists: no key is accepted.
PRODUCT_ID = None
BUY_URL = "https://esquaresoft.lemonsqueezy.com"
PORTAL_URL = "https://esquaresoft.lemonsqueezy.com/billing"

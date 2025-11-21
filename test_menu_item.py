from app import settings
from app.business_logic import get_effective_menu
print(settings.get_menu(force_refresh=True))   # see what settings returns
print(get_effective_menu())                    # see canonical menu business logic will use

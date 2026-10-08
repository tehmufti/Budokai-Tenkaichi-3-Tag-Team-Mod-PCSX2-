"""Install the shared boot hook in the explicitly selected portable runtime."""
from native_map import SERIAL
import runtime_profile
import game_profile
import guest_loading_screen

if __name__ == '__main__':
    guest_loading_screen.CHEAT = runtime_profile.CHEATS / game_profile.cheat_name(SERIAL)
    print(guest_loading_screen.install_cheat(guest_loading_screen.CHEAT))

import time
import pygame
import pymunk
import pymunk.pygame_util
import sys
import os
import argparse
from youtube import get_live_stream, get_new_live_chat_messages, get_live_chat_id, get_subscriber_count, validate_live_stream_id
from config import config
from atlas import create_texture_atlas
from pathlib import Path
from chunk import get_block, clean_chunks, delete_block, chunks
from constants import BLOCK_SCALE_FACTOR, BLOCK_SIZE, CHUNK_HEIGHT, CHUNK_WIDTH, INTERNAL_HEIGHT, INTERNAL_WIDTH, FRAMERATE
from pickaxe import Pickaxe
from camera import Camera
from sound import SoundManager
from tnt import Tnt, MegaTnt
import asyncio
import threading
import random
from hud import Hud
from collections import deque

# Linux environment එකේ display එක හඳුනා ගැනීමට hint එකක් ලබා දීම
os.environ['SDL_VIDEODRIVER'] = 'x11'

# --- YouTube ID එක හඳුනා ගැනීමේ ශ්‍රිතය ---
def extract_video_id(input_str):
    if not input_str: return None
    if "youtube.com/watch?v=" in input_str: return input_str.split("v=")[1].split("&")[0]
    elif "youtu.be/" in input_str: return input_str.split("youtu.be/")[1].split("?")[0]
    return input_str

parser = argparse.ArgumentParser()
parser.add_argument('--stream_id', type=str, help='YouTube Stream ID or Full Link')
args, unknown = parser.parse_known_args()

if args.stream_id:
    config["LIVESTREAM_ID"] = extract_video_id(args.stream_id)
    config["CHAT_CONTROL"] = True
# ----------------------------------------

asyncio_loop = asyncio.new_event_loop()
def start_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=start_event_loop, args=(asyncio_loop,), daemon=True).start()

def game():
    window_width, window_height = 1080, 1920
    pygame.init()
    
    # Audio නිසා crash වීම වැළැක්වීම
    try:
        pygame.mixer.init()
    except Exception as e:
        print(f"Audio init failed: {e}. Continuing without sound.")

    clock = pygame.time.Clock()
    space = pymunk.Space()
    space.gravity = (0, 1000)

    # මුලින්ම තිරය නිර්මාණය කර එය කළු වර්ණයෙන් පුරවන්න
    screen = pygame.display.set_mode((window_width, window_height))
    screen.fill((0, 0, 0))
    pygame.display.flip()

    assets_dir = Path(__file__).parent.parent / "src/assets"
    (texture_atlas, atlas_items) = create_texture_atlas(assets_dir)
    
    # Background image load කිරීම
    try:
        background_raw = pygame.image.load(assets_dir / "background.png")
        background_image = pygame.transform.scale(background_raw, (int(1080 * 1.5), int(1920 * 1.5)))
    except:
        background_image = pygame.Surface((1080, 1920)) # Fail-safe
        background_image.fill((30, 30, 30))

    texture_atlas = pygame.transform.scale(texture_atlas, (texture_atlas.get_width() * BLOCK_SCALE_FACTOR, texture_atlas.get_height() * BLOCK_SCALE_FACTOR))

    for cat in atlas_items:
        for item in atlas_items[cat]:
            x, y, w, h = atlas_items[cat][item]
            atlas_items[cat][item] = (x * BLOCK_SCALE_FACTOR, y * BLOCK_SCALE_FACTOR, w * BLOCK_SCALE_FACTOR, h * BLOCK_SCALE_FACTOR)

    sound_manager = SoundManager()
    internal_surface = pygame.Surface((INTERNAL_WIDTH, INTERNAL_HEIGHT))
    pickaxe = Pickaxe(space, INTERNAL_WIDTH // 2, INTERNAL_HEIGHT // 2, texture_atlas.subsurface(atlas_items["pickaxe"]["wooden_pickaxe"]), sound_manager)

    tnt_list = []
    camera = Camera()
    hud = Hud(texture_atlas, atlas_items)
    explosions = []

    last_tnt_spawn = last_yt_poll = last_queues_pop = pygame.time.get_ticks()
    
    live_chat_id = None
    if config["CHAT_CONTROL"]:
        # YouTube chat ID එක ලබා ගැනීම (මෙය backend එකේ සිදු වේ)
        pass

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False

        current_time = pygame.time.get_ticks()
        dt_ms = clock.get_time()

        space.step(1 / FRAMERATE)
        pickaxe.update(current_time)
        camera.update(pickaxe.body.position.y)

        # Drawing logic
        internal_surface.blit(background_image, (-100, -100))
        
        start_y = int(pickaxe.body.position.y // (CHUNK_HEIGHT * BLOCK_SIZE) - 2)
        clean_chunks(start_y, space)
        for cx in range(-1, 2):
            for cy in range(start_y, start_y + 5):
                for y in range(CHUNK_HEIGHT):
                    for x in range(CHUNK_WIDTH):
                        b = get_block(cx, cy, x, y, texture_atlas, atlas_items, space)
                        if b: 
                            b.update(space, hud, current_time)
                            b.draw(internal_surface, camera)

        for t in tnt_list: t.update(tnt_list, explosions, camera, current_time); t.draw(internal_surface, camera)
        pickaxe.draw(internal_surface, camera)
        for e in explosions: e.update(dt_ms); e.draw(internal_surface, camera)
        explosions = [e for e in explosions if e.particles]
        
        hud.draw(internal_surface, pickaxe.body.position.y, False, "Fast")
        
        # තිරය මතට ඇඳීම
        scaled_surface = pygame.transform.scale(internal_surface, (window_width, window_height))
        screen.blit(scaled_surface, (0, 0))
        pygame.display.flip()
        clock.tick(FRAMERATE)

    pygame.quit()

if __name__ == "__main__":
    game()

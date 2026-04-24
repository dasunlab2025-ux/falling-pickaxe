import time
import pygame
import pymunk
import pymunk.pygame_util
import sys
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

# --- YouTube ID එක ලින්ක් එකකින් වුවද වෙන් කර හඳුනාගැනීමේ ශ්‍රිතය ---
def extract_video_id(input_str):
    if not input_str:
        return None
    # සාමාන්‍ය ලින්ක් එකක් නම් (watch?v=)
    if "youtube.com/watch?v=" in input_str:
        return input_str.split("v=")[1].split("&")[0]
    # කෙටි ලින්ක් එකක් නම් (youtu.be/)
    elif "youtu.be/" in input_str:
        return input_str.split("youtu.be/")[1].split("?")[0]
    # දැනටමත් ID එකක් නම්
    return input_str

parser = argparse.ArgumentParser()
parser.add_argument('--stream_id', type=str, help='YouTube Stream ID or Full Link')
args, unknown = parser.parse_known_args()

if args.stream_id:
    final_id = extract_video_id(args.stream_id)
    config["LIVESTREAM_ID"] = final_id
    config["CHAT_CONTROL"] = True  # ID එකක් ලැබුණු සැණින් Chat Control ක්‍රියාත්මක වේ
    print(f"Target Stream ID: {final_id}")
# ------------------------------------------------------------------

# Track key states
key_t_pressed = False
key_m_pressed = False

live_stream = None
live_chat_id = None
subscribers = None

if config["CHAT_CONTROL"] == True:
    print("Checking for specific live stream...")
    if config["LIVESTREAM_ID"] is not None and config["LIVESTREAM_ID"] != "":
        stream_id = validate_live_stream_id(config["LIVESTREAM_ID"])
        live_stream = get_live_stream(stream_id)

    if live_stream:
        print("Live stream found:", live_stream["snippet"]["title"])
        print("Fetching live chat ID...")
        live_chat_id = get_live_chat_id(live_stream["id"])
    else:
        print("No specific live stream found. Running in Auto mode.")

    if live_chat_id:
        print("Live chat ID found:", live_chat_id)
    
    if config["CHANNEL_ID"]:
        subscribers = get_subscriber_count(config["CHANNEL_ID"])

# Queues for chat
tnt_queue = deque()
tnt_queue_authors = set()
tnt_superchat_queue = deque()
tnt_superchat_authors = set()
fast_slow_queue = deque()
fast_slow_authors = set()
big_queue = deque()
big_authors = set()
pickaxe_queue = deque()
pickaxe_authors = set()
mega_tnt_queue = deque()

async def handle_youtube_poll():
    global subscribers 
    if subscribers is not None:
        new_subscribers = get_subscriber_count(config["CHANNEL_ID"])
        if new_subscribers and new_subscribers > subscribers:
            mega_tnt_queue.append("New Subscriber") 
            subscribers = new_subscribers 

    new_messages = get_new_live_chat_messages(live_chat_id)
    for message in new_messages:
        author = message["author"]
        text = message["message"].lower()
        is_sc = message["sc_details"] or message["ss_details"]

        if "tnt" in text and author not in tnt_queue_authors:
            tnt_queue.append(author)
            tnt_queue_authors.add(author)

        if is_sc and author not in tnt_superchat_authors:
            tnt_superchat_queue.append((author, text))
            tnt_superchat_authors.add(author)

        if "fast" in text and author not in fast_slow_authors:
            fast_slow_queue.append((author, "Fast"))
            fast_slow_authors.add(author)
        elif "slow" in text and author not in fast_slow_authors:
            fast_slow_queue.append((author, "Slow"))
            fast_slow_authors.add(author)

        if "big" in text and author not in big_authors:
            big_queue.append(author)
            big_authors.add(author)

        # Pickaxe types
        for p_type in ["wood", "stone", "iron", "gold", "diamond", "netherite"]:
            if p_type in text and author not in pickaxe_authors:
                pickaxe_queue.append((author, f"{p_type}_pickaxe"))
                pickaxe_authors.add(author)

def start_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

asyncio_loop = asyncio.new_event_loop()
threading.Thread(target=start_event_loop, args=(asyncio_loop,), daemon=True).start()

def game():
    window_width, window_height = 1080, 1920
    pygame.init()
    clock = pygame.time.Clock()
    space = pymunk.Space()
    space.gravity = (0, 1000)

    screen = pygame.display.set_mode((window_width, window_height)) 
    scaled_surface = pygame.Surface((window_width, window_height)).convert()
    
    # Assets
    assets_dir = Path(__file__).parent.parent / "src/assets"
    (texture_atlas, atlas_items) = create_texture_atlas(assets_dir)
    
    background_image = pygame.transform.scale(pygame.image.load(assets_dir / "background.png"), (int(1080 * 1.5), int(1920 * 1.5)))
    texture_atlas = pygame.transform.scale(texture_atlas, (texture_atlas.get_width() * BLOCK_SCALE_FACTOR, texture_atlas.get_height() * BLOCK_SCALE_FACTOR))

    for cat in atlas_items:
        for item in atlas_items[cat]:
            x, y, w, h = atlas_items[cat][item]
            atlas_items[cat][item] = (x * BLOCK_SCALE_FACTOR, y * BLOCK_SCALE_FACTOR, w * BLOCK_SCALE_FACTOR, h * BLOCK_SCALE_FACTOR)

    sound_manager = SoundManager()
    internal_surface = pygame.Surface((INTERNAL_WIDTH, INTERNAL_HEIGHT))
    pickaxe = Pickaxe(space, INTERNAL_WIDTH // 2, INTERNAL_HEIGHT // 2, texture_atlas.subsurface(atlas_items["pickaxe"]["wooden_pickaxe"]), sound_manager)

    # Intervals
    last_tnt_spawn = last_random_pickaxe = last_enlarge = last_fast_slow = last_yt_poll = last_queues_pop = last_save_progress = pygame.time.get_ticks()
    tnt_spawn_interval = 5000
    tnt_list = []
    camera = Camera()
    hud = Hud(texture_atlas, atlas_items)
    explosions = []
    fast_slow_active = False
    fast_slow_mode = "Fast"

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False

        current_time = pygame.time.get_ticks()
        dt_ms = clock.get_time()

        # Physics Step
        step = 1 / FRAMERATE
        if fast_slow_active: step = 1 / (FRAMERATE / 2) if fast_slow_mode == "Fast" else 1 / (FRAMERATE * 2)
        space.step(step)

        # Updates
        pickaxe.update(current_time)
        camera.update(pickaxe.body.position.y)

        # Logic
        if (not config["CHAT_CONTROL"] or not tnt_queue) and current_time - last_tnt_spawn >= tnt_spawn_interval:
            tnt_list.append(Tnt(space, pickaxe.body.position.x, pickaxe.body.position.y - 100, texture_atlas, atlas_items, sound_manager))
            last_tnt_spawn = current_time
            tnt_spawn_interval = random.randint(5000, 30000)

        if live_chat_id and current_time - last_yt_poll >= (config["YT_POLL_INTERVAL_SECONDS"] * 1000):
            last_yt_poll = current_time
            asyncio.run_coroutine_threadsafe(handle_youtube_poll(), asyncio_loop)

        if current_time - last_queues_pop >= (config["QUEUES_POP_INTERVAL_SECONDS"] * 1000):
            last_queues_pop = current_time
            if tnt_queue:
                author = tnt_queue.popleft()
                tnt_queue_authors.discard(author)
                tnt_list.append(Tnt(space, pickaxe.body.position.x, pickaxe.body.position.y - 100, texture_atlas, atlas_items, sound_manager, owner_name=author))

        # Drawing
        screen.fill((0, 0, 0))
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
        
        hud.draw(internal_surface, pickaxe.body.position.y, fast_slow_active, fast_slow_mode)
        pygame.transform.scale(internal_surface, (window_width, window_height), scaled_surface)
        screen.blit(scaled_surface, (0, 0))

        pygame.display.flip()
        clock.tick(FRAMERATE)

    pygame.quit()

if __name__ == "__main__":
    game()

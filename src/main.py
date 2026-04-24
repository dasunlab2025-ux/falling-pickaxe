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

# --- GitHub Actions හරහා එවන Stream ID එක කියවීම ---
parser = argparse.ArgumentParser()
parser.add_argument('--stream_id', type=str, help='YouTube Stream ID')
args, unknown = parser.parse_known_args()

if args.stream_id:
    config["LIVESTREAM_ID"] = args.stream_id
    config["CHAT_CONTROL"] = True  # ID එකක් ලැබුණොත් Chat Control ඉබේම On කරයි
# --------------------------------------------------

# Track key states
key_t_pressed = False
key_m_pressed = False

live_stream = None
live_chat_id = None
subscribers = None

if config["CHAT_CONTROL"] == True:
    print("Checking for specific live stream")
    if config["LIVESTREAM_ID"] is not None and config["LIVESTREAM_ID"] != "":
        stream_id = validate_live_stream_id(config["LIVESTREAM_ID"])
        live_stream = get_live_stream(stream_id)

    if live_stream is None:
        print("No specific live stream found. App will run without it.")
    else:
        print("Live stream found:", live_stream["snippet"]["title"])

    if live_stream is not None:
        print("Fetching live chat ID...")
        live_chat_id = get_live_chat_id(live_stream["id"])

    if live_chat_id is None:
        print("No live chat ID found. App will run without it.")
    else:
        print("Live chat ID found:", live_chat_id)

    if(config["CHANNEL_ID"] is not None and config["CHANNEL_ID"] != ""):
        print("Fetching subscribers count...")
        subscribers = get_subscriber_count(config["CHANNEL_ID"])

    if subscribers is None:
        print("No subscribers count found. App will run without it.")
    else:
        print("Subscribers count found:", subscribers)

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
        if new_subscribers is not None and new_subscribers > subscribers:
            mega_tnt_queue.append("New Subscriber") 
            subscribers = new_subscribers 

    new_messages = get_new_live_chat_messages(live_chat_id)

    for message in new_messages:
        author = message["author"]
        text = message["message"]
        is_superchat = message["sc_details"] is not None
        is_supersticker = message["ss_details"] is not None

        text_lower = text.lower()

        if "tnt" in text_lower:
            if author not in tnt_queue_authors:
                tnt_queue.append(author)
                tnt_queue_authors.add(author)
                print(f"Added {author} to regular TNT queue")

        if is_superchat or is_supersticker:
            if author not in tnt_superchat_authors:
                 tnt_superchat_queue.append((author, text))
                 tnt_superchat_authors.add(author)
                 print(f"Added {author} to Superchat TNT queue")

        if "fast" in text.lower() and author not in fast_slow_authors:
            fast_slow_queue.append((author, "Fast"))
            fast_slow_authors.add(author)
        elif "slow" in text.lower() and author not in fast_slow_authors:
            fast_slow_queue.append((author, "Slow"))
            fast_slow_authors.add(author)

        if "big" in text.lower() and author not in big_authors:
            big_queue.append(author)
            big_authors.add(author)

        if "wood" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "wooden_pickaxe"))
                 pickaxe_authors.add(author)
        elif "stone" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "stone_pickaxe"))
                 pickaxe_authors.add(author)
        elif "iron" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "iron_pickaxe"))
                 pickaxe_authors.add(author)
        elif "gold" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "golden_pickaxe"))
                 pickaxe_authors.add(author)
        elif "diamond" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "diamond_pickaxe"))
                 pickaxe_authors.add(author)
        elif "netherite" in text_lower:
             if author not in pickaxe_authors:
                 pickaxe_queue.append((author, "netherite_pickaxe"))
                 pickaxe_authors.add(author)

def start_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

asyncio_loop = asyncio.new_event_loop()
threading.Thread(target=start_event_loop, args=(asyncio_loop,), daemon=True).start()

def game():
    # Vertical Live Stream සයිස් එක
    window_width = 1080
    window_height = 1920

    pygame.init()
    clock = pygame.time.Clock()

    space = pymunk.Space()
    space.gravity = (0, 1000)

    screen_size = (window_width, window_height)
    screen = pygame.display.set_mode(screen_size) # No Resize, Fixed 1080x1920
    scaled_surface = pygame.Surface(screen_size).convert()
    pygame.display.set_caption("Falling Pickaxe")

    # set icon
    icon_path = Path(__file__).parent.parent / "src/assets/pickaxe" / "diamond_pickaxe.png"
    if icon_path.exists():
        icon = pygame.image.load(icon_path)
        pygame.display.set_icon(icon)

    internal_surface = pygame.Surface((INTERNAL_WIDTH, INTERNAL_HEIGHT))

    assets_dir = Path(__file__).parent.parent / "src/assets"
    (texture_atlas, atlas_items) = create_texture_atlas(assets_dir)

    background_image = pygame.image.load(assets_dir / "background.png")
    background_scale_factor = 1.5
    background_width = int(background_image.get_width() * background_scale_factor)
    background_height = int(background_image.get_height() * background_scale_factor)
    background_image = pygame.transform.scale(background_image, (background_width, background_height))

    texture_atlas = pygame.transform.scale(texture_atlas,
                                        (texture_atlas.get_width() * BLOCK_SCALE_FACTOR,
                                        texture_atlas.get_height() * BLOCK_SCALE_FACTOR))

    for category in atlas_items:
        for item in atlas_items[category]:
            x, y, w, h = atlas_items[category][item]
            atlas_items[category][item] = (x * BLOCK_SCALE_FACTOR, y * BLOCK_SCALE_FACTOR, w * BLOCK_SCALE_FACTOR, h * BLOCK_SCALE_FACTOR)

    sound_manager = SoundManager()
    # Sound loading...
    for s_name, s_file, vol in [("tnt", "tnt.mp3", 0.3), ("stone1", "stone1.wav", 0.5), ("grass1", "grass1.wav", 0.1)]:
        p = assets_dir / "sounds" / s_file
        if p.exists(): sound_manager.load_sound(s_name, p, vol)

    pickaxe = Pickaxe(space, INTERNAL_WIDTH // 2, INTERNAL_HEIGHT // 2, texture_atlas.subsurface(atlas_items["pickaxe"]["wooden_pickaxe"]), sound_manager)

    last_tnt_spawn = pygame.time.get_ticks()
    tnt_spawn_interval = 1000 * random.uniform(config["TNT_SPAWN_INTERVAL_SECONDS_MIN"], config["TNT_SPAWN_INTERVAL_SECONDS_MAX"])
    tnt_list = [] 

    last_random_pickaxe = pygame.time.get_ticks()
    random_pickaxe_interval = 1000 * random.uniform(config["RANDOM_PICKAXE_INTERVAL_SECONDS_MIN"], config["RANDOM_PICKAXE_INTERVAL_SECONDS_MAX"])

    last_enlarge = pygame.time.get_ticks()
    enlarge_interval = 1000 * random.uniform(config["PICKAXE_ENLARGE_INTERVAL_SECONDS_MIN"], config["PICKAXE_ENLARGE_INTERVAL_SECONDS_MAX"])
    enlarge_duration = 1000 * config["PICKAXE_ENLARGE_DURATION_SECONDS"]

    fast_slow_active = False
    fast_slow = "Fast"
    fast_slow_interval = 1000 * random.uniform(config["FAST_SLOW_INTERVAL_SECONDS_MIN"], config["FAST_SLOW_INTERVAL_SECONDS_MAX"])
    last_fast_slow = pygame.time.get_ticks()

    camera = Camera()
    hud = Hud(texture_atlas, atlas_items)
    explosions = []

    yt_poll_interval = 1000 * config["YT_POLL_INTERVAL_SECONDS"]
    last_yt_poll = pygame.time.get_ticks()
    save_progress_interval = 1000 * config["SAVE_PROGRESS_INTERVAL_SECONDS"]
    last_save_progress = pygame.time.get_ticks()
    queues_pop_interval = 1000 * config["QUEUES_POP_INTERVAL_SECONDS"]
    last_queues_pop = pygame.time.get_ticks()

    running = True
    user_quit = False
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                user_quit = True

        dt_ms = clock.get_time()
        current_time = pygame.time.get_ticks()

        step_speed = 1 / FRAMERATE 
        if fast_slow_active and fast_slow == "Fast":
            step_speed = 1 / (FRAMERATE / 2)
        elif fast_slow_active and fast_slow == "Slow":
            step_speed = 1 / (FRAMERATE * 2)

        space.step(step_speed)

        start_chunk_y = int(pickaxe.body.position.y // (CHUNK_HEIGHT * BLOCK_SIZE) - 1) - 1
        end_chunk_y = int(pickaxe.body.position.y + INTERNAL_HEIGHT) // (CHUNK_HEIGHT * BLOCK_SIZE)  + 1

        pickaxe.update(current_time)
        camera.update(pickaxe.body.position.y)

        screen.fill((0, 0, 0))
        internal_surface.blit(background_image, ((INTERNAL_WIDTH - background_width) // 2, (INTERNAL_HEIGHT - background_height) // 2))

        # --- Spawn Logic ---
        if (not config["CHAT_CONTROL"] or (not tnt_queue and not tnt_superchat_queue)) and current_time - last_tnt_spawn >= tnt_spawn_interval:
             new_tnt = Tnt(space, pickaxe.body.position.x, pickaxe.body.position.y - 100, texture_atlas, atlas_items, sound_manager)
             tnt_list.append(new_tnt)
             last_tnt_spawn = current_time
             tnt_spawn_interval = 1000 * random.uniform(config["TNT_SPAWN_INTERVAL_SECONDS_MIN"], config["TNT_SPAWN_INTERVAL_SECONDS_MAX"])

        # Update TNTs
        for tnt in tnt_list:
            tnt.update(tnt_list, explosions, camera, current_time)

        # Poll Youtube
        if live_chat_id is not None and current_time - last_yt_poll >= yt_poll_interval:
            last_yt_poll = current_time
            asyncio.run_coroutine_threadsafe(handle_youtube_poll(), asyncio_loop)

        # Process chat queues
        if config["CHAT_CONTROL"] and current_time - last_queues_pop >= queues_pop_interval:
            last_queues_pop = current_time
            if tnt_queue:
                author = tnt_queue.popleft()
                tnt_queue_authors.discard(author)
                tnt_list.append(Tnt(space, pickaxe.body.position.x, pickaxe.body.position.y - 100, texture_atlas, atlas_items, sound_manager, owner_name=author))
            
            if mega_tnt_queue:
                author = mega_tnt_queue.popleft()
                tnt_list.append(MegaTnt(space, pickaxe.body.position.x, pickaxe.body.position.y - 100, texture_atlas, atlas_items, sound_manager, owner_name=author))

        # --- Drawing ---
        clean_chunks(start_chunk_y, space)
        for chunk_x in range(-1, 2):
            for chunk_y in range(start_chunk_y, end_chunk_y):
                for y in range(CHUNK_HEIGHT):
                    for x in range(CHUNK_WIDTH):
                        block = get_block(chunk_x, chunk_y, x, y, texture_atlas, atlas_items, space)
                        if block:
                            block.update(space, hud, current_time)
                            block.draw(internal_surface, camera)

        pickaxe.draw(internal_surface, camera)
        for tnt in tnt_list: tnt.draw(internal_surface, camera)
        for explosion in explosions:
            explosion.update(dt_ms)
            explosion.draw(internal_surface, camera)
        explosions = [e for e in explosions if e.particles]

        hud.draw(internal_surface, pickaxe.body.position.y, fast_slow_active, fast_slow)

        # Scale to window
        pygame.transform.scale(internal_surface, (window_width, window_height), scaled_surface)
        screen.blit(scaled_surface, (0, 0))

        # Save progress
        if current_time - last_save_progress >= save_progress_interval:
            last_save_progress = current_time
            log_dir = Path(__file__).parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "progress.txt", "a+") as f:
                f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')} | Y: {-int(pickaxe.body.position.y // BLOCK_SIZE)}\n")

        pygame.display.flip()
        clock.tick(FRAMERATE)

    pygame.quit()
    sys.exit(0 if user_quit else 1)

if __name__ == "__main__":
    game()

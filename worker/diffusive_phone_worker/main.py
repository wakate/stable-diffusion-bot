import os
import time
import uuid
import json
import base64
from io import BytesIO
import logging

import asyncio
import websockets

from diffusers import StableDiffusionPipeline
import torch

DIFFUSION_TOKEN = os.environ['DIFFUSION_TOKEN']
SERVER = os.environ.get('SERVER', 'ws://localhost:8000/ws')
SERVER_SECRET = os.environ['SERVER_SECRET']
N_LIMIT = os.environ.get('N_LIMIT', 1)

# TODO: add authentication

logging.basicConfig(level=logging.INFO)

load_start = time.time()
logging.info('Loading model...')
pipe = StableDiffusionPipeline.from_pretrained(
    "CompVis/stable-diffusion-v1-4",
    revision='fp16',
    torch_dtype=torch.float16,
    use_auth_token=DIFFUSION_TOKEN
)
pipe.to('cuda')
load_end = time.time()
logging.info(f'Loading model done in {load_end - load_start} seconds')

worker_id = uuid.uuid4()
logging.info(f'worker_id is {worker_id}')

async def connect():
    async with websockets.connect(SERVER) as websocket:
        logging.info('Connected!')
        await websocket.send(json.dumps({
            'kind': 'ready',
            'worker_id': str(worker_id),
            'n_limit': N_LIMIT,
            'secret': SERVER_SECRET,
        }))
        while True:
            # TODO: add some timeout if something hangs on the websocket?
            m = json.loads(await websocket.recv())
            prompt = m['prompt']
            options = m['options']
            logging.info(f'Running generation for prompt: "{prompt}" ({options})')

            n = options['n']
            assert(0 < n and n <= N_LIMIT)

            # TODO: this will always be in options?
            if 'seed' in options:
                options['generator'] = torch.Generator(device='cuda').manual_seed(options['seed'])
                del options['seed']

            inference_start = time.time()
            if n == 1:
                with torch.autocast('cuda'):
                    result = pipe(prompt, **options)

                image = result['sample'][0]
                is_nsfw = result['nsfw_content_detected'][0]
            else:
                with torch.autocast('cuda'):
                    result = pipe([prompt] * n, **options)

                image = result['sample']
                is_nsfw = result['nsfw_content_detected']

            inference_end = time.time()
            logging.info(f'Generation complete ({inference_end - inference_start} seconds)')

            def encode_image(image):
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                return base64.b64encode(buffer.getvalue()).decode('ascii')

            if n == 1:
                await websocket.send(json.dumps({
                    'kind': 'done',
                    'worker_id': str(worker_id),
                    'image':  encode_image(image),
                    'is_nsfw': is_nsfw
                }))
            else:
                await websocket.send(json.dumps({
                    'kind': 'done',
                    'worker_id': str(worker_id),
                    'image':  list(map(encode_image, image)),
                    'is_nsfw': is_nsfw
                }))

async def run():
    while True:
        logging.info('Attempting connection!')
        try:
            await connect()
        except (
            websockets.exceptions.WebSocketException,
            asyncio.exceptions.TimeoutError,
            ConnectionRefusedError
        ) as e:
            logging.warning(f'Connection closed; reconnecting in 5 seconds! ({e})')
            await asyncio.sleep(5)

asyncio.run(run())
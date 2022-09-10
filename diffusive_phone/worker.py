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

diffusion_token = os.environ['DIFFUSION_TOKEN']
# TODO: make this configurable
#server = os.environ['SERVER']
#key = os.environ['KEY']

# TODO: add authentication

logging.basicConfig(level=logging.INFO)

load_start = time.time()
logging.info('Loading model...')
pipe = StableDiffusionPipeline.from_pretrained(
    "CompVis/stable-diffusion-v1-4",
    revision='fp16',
    torch_dtype=torch.float16,
    use_auth_token=diffusion_token
)
pipe.to('cuda')
load_end = time.time()
logging.info(f'Loading model done in {load_end - load_start} seconds')

server = 'ws://localhost:8000/ws'
worker_id = uuid.uuid4()
logging.info(f'worker_id is {worker_id}')

async def connect():
    async with websockets.connect(server) as websocket:
        logging.info('Connected!')
        await websocket.send(json.dumps({
            'kind': 'ready',
            'worker_id': str(worker_id)
        }))
        while True:
            # TODO: add some timeout if something hangs on the websocket?
            m = json.loads(await websocket.recv())
            prompt = m['prompt']
            logging.info(f'Running generation for prompt: "{prompt}"')

            inference_start = time.time()
            with torch.autocast('cuda'):
                result = pipe(prompt)

            image = result['sample'][0]
            is_nsfw = result['nsfw_content_detected'][0]
            inference_end = time.time()

            logging.info(f'Generati9on complete ({inference_end - inference_start} seconds)')

            buffer = BytesIO()
            image.save(buffer, format='PNG')
            await websocket.send(json.dumps({
                'kind': 'done',
                'worker_id': str(worker_id),
                'image':  base64.b64encode(buffer.getvalue()).decode('ascii'),
                'is_nsfw': is_nsfw
            }))

async def run():
    while True:
        logging.info('Attempting connection!')
        try:
            await connect()
        except (
            websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.InvalidMessage,
            asyncio.exceptions.TimeoutError,
            ConnectionRefusedError
        ) as e:
            logging.warning(f'Connection closed; reconnecting in 5 seconds! ({e})')
            await asyncio.sleep(5)

asyncio.run(run())
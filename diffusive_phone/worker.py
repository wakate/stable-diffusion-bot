import os
import time
import uuid
import json
import base64
from io import BytesIO
import asyncio
import websockets

from diffusers import StableDiffusionPipeline
import torch

diffusion_token = os.environ['DIFFUSION_TOKEN']
# TODO: make this configurable
#server = os.environ['SERVER']
#key = os.environ['KEY']

load_start = time.time()
print('Loading model...')
pipe = StableDiffusionPipeline.from_pretrained(
    "CompVis/stable-diffusion-v1-4",
    revision='fp16',
    torch_dtype=torch.float16,
    use_auth_token=diffusion_token
)
pipe.to('cuda')
load_end = time.time()
print(f'Loading model done in {load_end - load_start} seconds')

server = 'ws://localhost:8000/ws'
worker_id = uuid.uuid4()
print(f'worker_id is {worker_id}')

async def connect():
    async with websockets.connect(server) as websocket:
        print('Connected!')
        await websocket.send(json.dumps({
            'kind': 'ready',
            'worker_id': str(worker_id)
        }))
        while True:
            m = json.loads(await websocket.recv())
            prompt = m['prompt']
            print(f'Running generation for prompt: "{prompt}"')

            with torch.autocast('cuda'):
                image = pipe(prompt)['sample'][0]

            print('Done.')

            buffer = BytesIO()
            image.save(buffer, format='PNG')
            await websocket.send(json.dumps({
                'kind': 'done',
                'worker_id': str(worker_id),
                'image':  base64.b64encode(buffer.getvalue()).decode('ascii')
            }))

async def run():
    while True:
        print('Attempting connection!')
        try:
            await connect()
        except (
            websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.InvalidMessage,
            asyncio.exceptions.TimeoutError,
            ConnectionRefusedError
        ) as e:
            print(f'Connection closed; reconnecting in 5 seconds! ({e})')
            await asyncio.sleep(5)

asyncio.run(run())
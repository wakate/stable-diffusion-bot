import os
import time
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
import asyncio

from typing import Union
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from diffusers import StableDiffusionPipeline
import torch

diffusion_token = os.environ['DIFFUSION_TOKEN']

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

app = FastAPI()

@app.get('/')
def read_root():
    return { 'Hello': 'World' }

class Query(BaseModel):
    prompt: str

inference_lock = asyncio.Lock()
@app.post('/query')
async def run_inference(query: Query):
    # Asyncronous calls seem to mess with inference, so we add a mutex here
    async with inference_lock:
        with torch.autocast('cuda'):
            image = pipe(query.prompt)['sample'][0]

    buffer = BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    return StreamingResponse(buffer, media_type='image/png')

# Below unfortunately doesn't work; it tries to load the model multiple times, running out of memory... :(
#def generate_image(prompt):
#    with torch.autocast('cuda'):
#        return pipe(prompt)['sample'][0]
#
#@app.post('/query')
#async def run_inference(query: Query):
#    with ProcessPoolExecutor() as executor:
#        image = await asyncio.get_running_loop().run_in_executor(executor, generate_image, query.prompt)
#
#    buffer = BytesIO()
#    image.save(buffer, format='PNG')
#    buffer.seek(0)
#    return StreamingResponse(buffer, media_type='image/png')
import os
from typing import Union
from fastapi import FastAPI
from pydantic import BaseModel

from diffusers import StableDiffusionPipeline

diffusion_token = os.environ['DIFFUSION_TOKEN']
print('Loading model...')
pipe = StableDiffusionPipeline.from_pretrained("CompVis/stable-diffusion-v1-4", use_auth_token=diffusion_token)
print('Loading model done.')

app = FastAPI()

@app.get('/')
def read_root():
    return { 'Hello': 'World' }

class Query(BaseModel):
    prompt: str

@app.post('/query')
async def run_inference(query: Query):
    with ProcessPoolExecutor(max_tasks=1) as executor:
        result = asyncio.get_running_loop().run_in_executor(exector, pipe, query.prompt)
    return result
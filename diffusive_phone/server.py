import io
import json
import base64
from datetime import datetime
import asyncio

from typing import Union
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

app = FastAPI()

@app.get('/', response_class=FileResponse)
def index():
    return 'index.html'

workers = {}
workers_lock = asyncio.Lock()
class Worker():
    def __init__(
        self,
        last_message_on: datetime,
        id: str,
        state: str,
        websocket: WebSocket,
        ):
        self.last_message_on = last_message_on
        self.id = id
        self.state = state
        self.websocket = websocket

    async def dispatch(self, prompt: str):
        try:
            await self.websocket.send_text(json.dumps({
                'kind': 'prompt',
                'prompt': prompt,
            }))

            m = json.loads(await self.websocket.receive_text())
            assert(m['kind'] == 'done')
            return io.BytesIO(base64.b64decode(m['image'].encode('ascii')))
        except WebSocketDisconnect:
            print(f'worker ({self.id}) disconnected!')
            self.state = 'dead'
            async with workers_lock:
                del workers[self.id]
            return None

@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    m = json.loads(await websocket.receive_text())
    worker = Worker(
        last_message_on=datetime.now(),
        id=m['worker_id'],
        state='ready',
        websocket=websocket
    )
    workers[worker.id] = worker
    print(f'worker ({worker.id}) connected!')

    while True:
        await asyncio.sleep(1)
        if worker.state == 'dead':
            break

class Query(BaseModel):
    prompt: str

@app.post('/query')
async def dispatch_inference(query: Query):
    async with workers_lock:
        for worker in workers.values():
            if worker.state == 'ready':
                worker_to_dispatch_to = worker
                worker_to_dispatch_to.state = 'busy'
                break

    # TODO: handle when there are no ready workers

    # TODO: handle when encoded_image is None (i.e. worker disconnected)
    image = await worker_to_dispatch_to.dispatch(query.prompt)
    worker_to_dispatch_to.state = 'ready'

    return StreamingResponse(image, media_type='image/png')
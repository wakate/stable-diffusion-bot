import enum
from datetime import datetime
import json
import io
from io import BytesIO
import base64
import os

import threading
import asyncio
import websockets

import discord
from discord.ext import commands

class WorkerState(enum.Enum):
    Ready = enum.auto()
    # TODO: Reserverd?
    Busy = enum.auto()
    Dead = enum.auto()

class Worker():
    def __init__(
        self,
        last_message_on: datetime,
        id: str,
        websocket,
    ):
        self.last_message_on = last_message_on
        self.id = id
        self.state = WorkerState.Ready
        self.websocket = websocket
        self.death_future = asyncio.get_event_loop().create_future()
        # TODO: handle disconnect

    def is_ready(self):
        return self.state == WorkerState.Ready

    def mark_busy(self):
        self.state = WorkerState.Busy

    async def dispatch(self, prompt: str):
        try:
            await self.websocket.send(json.dumps({
                'kind': 'prompt',
                'prompt': prompt,
            }))

            m = json.loads(await self.websocket.recv())
            assert(m['kind'] == 'done')
            print('response found!')
        except websockets.exceptions.WebSocketException as e:
            print(f'Encountered exception {e}')
            self.state = WorkerState.Dead
            self.death_future.set_value(None)
            return None

        self.state = WorkerState.Ready
        return {
            'image': io.BytesIO(base64.b64decode(m['image'].encode('ascii'))),
            'is_nsfw': m['is_nsfw'],
        }

    async def done(self):
       await self.death_future

# TODO: This isn't really a queue
class WorkQueue():
    def __init__(
        self
    ): 
        self.workers = {}
        self.workers_lock = asyncio.Lock()
        self.queue = asyncio.Queue()

    async def add_worker(self, worker):
        print(f'Adding worker: {worker.id}')
        async with self.workers_lock:
            self.workers[worker.id] = worker

        await worker.done()

        print(f'Removing worker: {worker.id}')
        async with self.workers_lock:
            del self.workers[worker.id]

    async def dispatch(self, prompt):
        chosen_worker = None
        while chosen_worker is None:
            async with self.workers_lock:
                for worker in self.workers.values():
                    if worker.is_ready():
                        chosen_worker = worker
                        worker.mark_busy()
            
            if chosen_worker is None:
                print('Couldn\'t find worker! sleeping for 1 second and trying again')
                await asyncio.sleep(1)
        
        print(f'Dispatching to worker {chosen_worker.id}')

        result = await chosen_worker.dispatch(prompt)

        return result

work_queue = WorkQueue()

async def ws_handler(ws):
    print('connection!!')
    m = json.loads(await ws.recv())
    worker = Worker(
        last_message_on=datetime.now(),
        id=m['worker_id'],
        websocket=ws,
    )
    await work_queue.add_worker(worker)

async def run_ws_server():
    async with websockets.serve(ws_handler, 'localhost', 8000):
        await asyncio.Future()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)

@bot.command()
async def generate(ctx, prompt):
    print(f'Running generation for prompt: "{prompt}" ({ctx})')

    result = await work_queue.dispatch(prompt)

    print(f'Done (is_nsfw={result["is_nsfw"]}).')

    if result['is_nsfw']:
        await ctx.reply('不適切な可能性のある内容が検出されました。生成をし直すか、別なプロンプトを試してください。')
    else:
        sent_msg = await ctx.reply(f'プロンプト: "{prompt}"', file=discord.File(result['image'], filename='result.png', description=prompt))

        def check(msg):
            return (
                msg.type == discord.MessageType.reply and
                msg.reference is not None and
                msg.reference.message_id == sent_msg.id and
                '提出' in msg.content
            )

        msg = await bot.wait_for('message', check=check)
        # TODO: handle
        await msg.reply('提出が完了しました!')

async def main():
    discord.utils.setup_logging()
    async with bot:
        # We intentionally create a reference here so this task doesn't get GC-ed.
        server = bot.loop.create_task(run_ws_server())
        await bot.start(os.environ['DISCORD_TOKEN'])

asyncio.run(main())
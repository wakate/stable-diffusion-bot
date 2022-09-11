import enum
from datetime import datetime
import json
import io
import base64
import os
import logging
import itertools
import random
import hashlib

import asyncio
import websockets

import discord
from discord.ext import commands

DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
WORKER_SECRET = os.environ['WORKER_SECRET']
IP = os.environ.get('IP', 'localhost')
PORT = os.environ.get('PORT', 8000)
PING_TIMEOUT=150
MAX_SIZE=512 * (2 ** 20) # 512MB

def hash(s):
    m = hashlib.sha256()
    m.update(s.encode('ascii'))
    return m.digest()

WORKER_SECRET = hash(WORKER_SECRET)

class WorkerState(enum.Enum):
    Ready = enum.auto()
    # TODO: Reserved?
    Busy = enum.auto()
    Dead = enum.auto()

class Worker():
    def __init__(
        self,
        last_message_on: datetime,
        id: str,
        n_limit: int,
        remote_address,
        websocket,
    ):
        self.last_message_on = last_message_on
        self.id = id
        self.n_limit = n_limit
        self.remote_address = remote_address
        self.state = WorkerState.Ready
        self.websocket = websocket
        # TODO: use websocket wait for disconnect coroutine?
        self.death_future = asyncio.get_event_loop().create_future()
        self.logger = logging.getLogger('worker')
        # TODO: handle disconnect

    def is_ready(self):
        return self.state == WorkerState.Ready

    def mark_busy(self):
        self.state = WorkerState.Busy

    async def dispatch(self, prompt: str, options):
        try:
            # TODO: add some timeout here in case something hangs?
            await self.websocket.send(json.dumps({
                'kind': 'prompt',
                'prompt': prompt,
                'options': options,
            }))

            payload = await self.websocket.recv()
            self.logger.info(f'Received generation result ({len(payload)} bytes)')
            m = json.loads(payload)
            assert(m['kind'] == 'done')
            self.last_message_on=datetime.now()
        except websockets.exceptions.WebSocketException as e:
            self.logger.warning(f'Encountered exception {e}')
            self.state = WorkerState.Dead
            self.death_future.set_result(None)
            return None

        self.state = WorkerState.Ready

        def decode_image(s):
            return io.BytesIO(base64.b64decode(s.encode('ascii')))

        if isinstance(m['image'], list):
            return {
                'image': list(map(decode_image, m['image'])),
                'is_nsfw': m['is_nsfw']
            }
        else:
            return {
                'image': decode_image(m['image']),
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
        self.logger = logging.getLogger('work_queue')

    async def add_worker(self, worker):
        self.logger.info(f'Adding worker: {worker.id} ({worker.remote_address})')
        async with self.workers_lock:
            self.workers[worker.id] = worker

        await worker.done()

        self.logger.info(f'Removing worker: {worker.id} ({worker.remote_address})')
        async with self.workers_lock:
            del self.workers[worker.id]

    async def dispatch(self, prompt, options):
        chosen_worker = None
        while chosen_worker is None:
            async with self.workers_lock:
                logging.info({ id: (worker.remote_address, worker.state) for (id, worker) in self.workers.items() })
                for worker in self.workers.values():
                    if worker.is_ready() and (options['n'] <= worker.n_limit):
                        chosen_worker = worker
                        worker.mark_busy()
                        break
            
            # TODO: if this happens a lot, maybe send a message saying
            # workers are congested?
            if chosen_worker is None:
                self.logger.warning('Couldn\'t find worker! sleeping for 5 seconds, then trying again')
                await asyncio.sleep(5)
        
        self.logger.info(f'Dispatching to worker {chosen_worker.id}')

        return (await chosen_worker.dispatch(prompt, options))

work_queue = WorkQueue()

async def ws_handler(ws):
    try:
        m = json.loads(await ws.recv())
        if hash(m['secret']) != WORKER_SECRET:
            logging.error(f'Invalid worker secret: "{m["secret"]}"')
        else:
            worker = Worker(
                last_message_on=datetime.now(),
                id=m['worker_id'],
                n_limit=m['n_limit'],
                remote_address=ws.remote_address,
                websocket=ws,
            )
            await work_queue.add_worker(worker)
    except Exception as e:
        logging.error(f'Exception occurred when handling websocket connection: {e}')

async def run_ws_server():
    async with websockets.serve(ws_handler, IP, PORT, ping_timeout=PING_TIMEOUT, max_size=MAX_SIZE):
        await asyncio.Future()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)

def parse_prompt(prompt):
    words = prompt.split(' ')

    def before_and_after(p, l):
        return (itertools.takewhile(p, l), itertools.dropwhile(p, l))

    options, prompt = before_and_after(lambda s: len(s.split('=')) == 2, words)
    options = {
        x[0]: x[1]
        for x
        in [
            option.split('=')
            for option
            in options
        ]
    }
    prompt = ' '.join(prompt)

    ret = {}
    allowed_options = {
        'guidance_scale': float,
        # TODO: clamp
        'num_inference_steps': int,
        # TODO: specifying height, weight larger than 512 results in OOM
        'width': lambda x: min(512, int(x)),
        'height': lambda x: min(512, int(x)),
        'eta': float,
        'seed': int,
        'n': int,
    }

    for (name, parser) in allowed_options.items():
        if name in options:
            ret[name] = parser(options[name])

    # TODO: I can't seem to make this work :(
    # if 'aspect_ratio' in options:
    #     width, height = list(map(float, options['aspect_ratio'].split('x')))
    #     multiple = math.sqrt((512/8)*(512/8)/width/height)
    #     # width and height need to be integer multiples of 8
    #     width, height = int(width*multiple)*8, int(height*multiple)*8
    #     if width > 0 and height > 0:
    #         ret['width'] = width
    #         ret['height'] = height

    return (ret, prompt)

# TODO: handle syntax errors (possibly print a help message?)
@bot.command()
async def generate(ctx, *, prompt):
    raw_prompt = prompt
    options, prompt = parse_prompt(prompt)
    if 'seed' not in options:
        # TODO think about this
        options['seed'] = random.randint(0, 1000000)
    if 'n' not in options:
        options['n'] = 1
    logging.info(f'Running generation for prompt: "{prompt}" ({options}) (raw prompt: {raw_prompt}) ({ctx})')

    result = await work_queue.dispatch(prompt, options)

    while result is None:
        logging.warning(f'Retrying dispatch in 10 seconds')
        await asyncio.sleep(10)
        result = await work_queue.dispatch(prompt, options)

    logging.info(f'Done (is_nsfw={result["is_nsfw"]}).')
    reply_msg = f'プロンプト: "{prompt}" ({options})'

    def create_file(image):
        return discord.File(image, filename='result.png', description=prompt)

    if isinstance(result['image'], list):
        sent_msg = await ctx.reply(reply_msg, files=list(map(create_file, result['image'])))
    else:
        if result['is_nsfw']:
            await ctx.reply('不適切な可能性のある内容が検出されました。生成をし直すか、別なプロンプトを試してください。')
            return
        else:
            sent_msg = await ctx.reply(reply_msg, file=create_file(result['image']))

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
        await bot.start(DISCORD_TOKEN)

asyncio.run(main())
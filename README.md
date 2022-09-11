# diffusive-phone

A gartic-phone-like game where the AI draws for you!

## howto

server:
```
$ cd server
$ poetry install
$ WORKER_SECRET='...' DISCORD_TOKEN='...' poetry run python diffusive_phone_server/main.py
```

worker:
```
$ cd worker
$ poetry install
$ SERVER_SECRET='...' DIFFUSION_TOKEN='...' poetry run python diffusive_phone_worker/main.py
```

## TODO

- [x] switch to using Discord-bot-based communication
- [ ] implement user authentication
- [ ] add progress indicator?
- [ ] generate multiple images at once?
- [x] use a worker queue for generating multiple images in parallel?

- [ ] deploy to AWS
  - domain name actually isn't really necessary...
- [ ] implement game
  - it would be nice if we could use buttons...
- [ ] implement control channel commands
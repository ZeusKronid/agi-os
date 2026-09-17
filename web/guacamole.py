"""Guacamole handshake and authenticated localhost WebSocket tunnel."""
import asyncio
import codecs
import uuid
from aiohttp import web, WSMsgType


def instruction(*values):
    return ','.join(f'{len(str(v))}.{v}' for v in values) + ';'


async def read_instruction(reader):
    # Handshake elements are UTF-8; lengths in the wire protocol count characters.
    values = []
    while True:
        raw = await reader.readuntil(b'.')
        if len(raw) > 9 or not raw[:-1].isdigit():
            raise ValueError('Invalid Guacamole instruction length')
        length = int(raw[:-1])
        if length > 65536:
            raise ValueError('Guacamole handshake too large')
        chars = ''
        decoder = codecs.getincrementaldecoder('utf-8')()
        while len(chars) < length:
            chars += decoder.decode(await reader.readexactly(1))
        values.append(chars)
        separator = await reader.readexactly(1)
        if separator == b';':
            return values
        if separator != b',':
            raise ValueError('Invalid Guacamole separator')


async def handshake(reader, writer, vnc_port):
    async def send(*values):
        writer.write(instruction(*values).encode())
        await writer.drain()
    await send('select', 'vnc')
    args = await read_instruction(reader)
    if args[0] != 'args':
        raise ValueError('guacd did not provide connection arguments')
    await send('size', 1280, 800, 96)
    await send('audio')
    await send('video')
    await send('image', 'image/png', 'image/jpeg')
    params = {'hostname': '127.0.0.1', 'port': str(vnc_port), 'read-only': 'false',
              'swap-red-blue': 'false', 'cursor': 'remote', 'color-depth': '24',
              'VERSION_1_5_0': 'VERSION_1_5_0'}
    await send('connect', *(params.get(arg, '') for arg in args[1:]))
    ready = await read_instruction(reader)
    if ready[0] != 'ready':
        raise ValueError('Guacamole: ' + ' '.join(ready))


async def tunnel(request):
    state = request.app['state']
    if not state.vm or not state.vm.running:
        raise web.HTTPConflict(text='Виртуальная машина ещё не запущена')
    reader, writer = await asyncio.open_connection('127.0.0.1', state.guacd_port)
    try:
        await asyncio.wait_for(handshake(reader, writer, state.vm.vnc_port), 15)
        ws = web.WebSocketResponse(protocols=('guacamole',), max_msg_size=1_000_000)
        await ws.prepare(request)
        await ws.send_str(instruction('', str(uuid.uuid4())))
        async def upstream():
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    # Empty-opcode instructions belong to the WebSocket tunnel.
                    if message.data.startswith('0.,'):
                        await ws.send_str(message.data)
                    else:
                        writer.write(message.data.encode())
                        await writer.drain()
        async def downstream():
            decoder = codecs.getincrementaldecoder('utf-8')()
            while data := await reader.read(65536):
                text = decoder.decode(data)
                if text:
                    await ws.send_str(text)
        tasks = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await ws.close()
        return ws
    finally:
        writer.close()
        await writer.wait_closed()

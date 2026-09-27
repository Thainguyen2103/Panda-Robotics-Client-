"""Browser microphone WebSocket transport and service entry point."""
import asyncio
import contextlib
import json

from aiohttp import web, WSMsgType
from groq import AsyncGroq

from config import settings
from server.voice.runtime.session import Session, acoustic_engine


async def socket_handler(request):
    if request.headers.get('Origin') != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=20)
    await ws.prepare(request)
    if not settings.GROQ_API_KEY:
        await ws.send_json(dict(event='error', text='Thiếu GROQ_API_KEY trong config/secrets.py hoặc môi trường.'))
        await ws.close()
        return ws
    continuous = request.query.get('mode') == 'continuous'
    engine = None
    tasks = []
    try:
        if continuous:
            description = 'Groq Whisper liên tục: không cần wake word'
        else:
            engine, description = acoustic_engine()
        async with AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=15, max_retries=0) as client:
            session = Session(ws, client, engine, continuous=continuous)
            await session.emit('ready', engine=description, calibrating=True,
                               mode='continuous' if continuous else 'wakeword')
            tasks = [asyncio.create_task(session.worker()), asyncio.create_task(session.watchdog())]
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    await session.feed(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
                elif msg.type == WSMsgType.TEXT:
                    try:
                        command = json.loads(msg.data).get('command')
                    except Exception:
                        command = None
                    if command == 'pause':
                        session.pause()
                    elif command == 'resume':
                        await session.resume()
    except Exception as exc:
        if not ws.closed:
            await ws.send_json(dict(event='error', text=f'Voice lỗi ({type(exc).__name__}). Kiểm tra cấu hình model/mic.'))
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                await task
        if engine:
            engine.delete()
        await ws.close()
    return ws


def make_app():
    app = web.Application()
    app.router.add_get('/ws', socket_handler)

    async def dashboard(request):
        raise web.HTTPFound('http://localhost:3000/')

    app.router.add_get('/', dashboard)
    return app


def main():
    web.run_app(make_app(), host='127.0.0.1', port=8765)


if __name__ == '__main__':
    main()

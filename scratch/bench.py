import sys
import time
sys.path.insert(0, '.')
from server.llm import engine

q = 'cái này, không phải cái này đâu nè.'

t0 = time.time()
norm_q = engine.normalize_user_question(q)
print(f'norm_q: {time.time()-t0:.3f}s')

t0 = time.time()
msgs = engine._get_messages(norm_q)
print(f'_get_messages: {time.time()-t0:.3f}s')
print('Num msgs:', len(msgs))
for m in msgs:
    print(f"   {m['role']}: {len(m['content'])} chars")

t0 = time.time()
stream = engine._stream_provider(engine._client, engine._provider_name, engine._model_name, msgs, 128, 0.25)
print(f'_stream_provider created: {time.time()-t0:.3f}s')

t0 = time.time()
first_chunk = next(stream)
print(f'First token received: {time.time()-t0:.3f}s -> {repr(first_chunk)}')

tokens = [first_chunk]
for c in stream:
    tokens.append(c)
print(f'Full stream finished: {time.time()-t0:.3f}s, total tokens: {len(tokens)}')

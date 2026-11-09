"""Close upstream resources even if authorization rejects an unstarted response."""
from starlette.responses import StreamingResponse


class GuardedStream(StreamingResponse):
    def __init__(self, upstream, content, **kwargs):
        self.upstream = upstream
        super().__init__(content, **kwargs)

    def close(self):
        self.upstream.close()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.close()

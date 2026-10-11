"""Measure queue ASGI response and concurrent health, with no app lifespan."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def measure(root, size):
    import offline_guard
    offline_guard.pytest_configure(None)
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix='royal-response-') as scratch:
        os.environ['SERIENDL_DATA_DIR'] = scratch
        import server
        from api.api_queue_router import api_queue_get
        from api.api_system_router import legacy_health
        from core.queue_jobs import new_job
        from fastapi import FastAPI
        from httpx2 import AsyncClient, ASGITransport
        state = server.state
        state.queue_jobs.clear()
        state.queue_job_by_slug.clear()
        state.picked.clear()
        state.fp_movies.clear()
        state.watchlist = []
        state.movie_subscriptions = []
        for i in range(size):
            job = new_job(f'fixture:{i}', title=f'Fixture movie {i}', job_id=f'job-{i}')
            state.queue_jobs[job['job_id']] = job
            state.queue_job_by_slug[job['slug']] = job['job_id']
            state.picked.add(job['slug'])
        # Exercise the same handlers and FastAPI JSON serialization; avoid
        # production auth/setup/lifespan and all integration startup effects.
        app = FastAPI()
        app.add_api_route('/queue', api_queue_get, methods=['GET'])
        app.add_api_route('/health', legacy_health, methods=['GET'])
        async def scenario():
            health, queue_times, heartbeat = [], [], []
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
                for _ in range(7):
                    started = time.perf_counter()
                    queue_task = asyncio.create_task(client.get('/queue'))
                    async def probe():
                        # Scheduled at the same time, behind the queue request.
                        response = await client.get('/health')
                        assert response.status_code == 200
                        return (time.perf_counter() - started) * 1000
                    probe_task = asyncio.create_task(probe())
                    health.append(await probe_task)
                    response = await queue_task
                    queue_times.append((time.perf_counter() - started) * 1000)
                    assert response.status_code == 200
                    assert response.json()['queue']['count'] == size
                    heartbeat.append(len(response.content))
            return {'size': size, 'health_ms': health, 'queue_ms': queue_times,
                    'health_median_ms': statistics.median(health),
                    'queue_median_ms': statistics.median(queue_times), 'response_bytes': heartbeat[0]}
        return asyncio.run(scenario())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--size', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.size:
        print(json.dumps(measure(args.root.resolve(), args.size)))
        return
    payload = {'description': 'in-process ASGI queue response and concurrently scheduled health; seven samples per size',
               'baseline': [], 'candidate': []}
    for size in (650, 1000, 5000):
        for label, root in [('baseline', args.baseline), ('candidate', args.candidate)]:
            call = subprocess.run([sys.executable, __file__, '--root', str(root), '--size', str(size)],
                                  capture_output=True, text=True, timeout=120)
            if call.returncode:
                raise RuntimeError(call.stderr[-4000:])
            payload[label].append(json.loads(call.stdout))
    args.output.write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps(payload))


if __name__ == '__main__':
    main()

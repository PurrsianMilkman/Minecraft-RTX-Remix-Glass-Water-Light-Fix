"""Fast, resumable download of one big file over several connections (what a browser does, which is why a browser is often much
faster than a single curl stream on GitHub's release downloads).

The file is cut into 16 MB chunks; N worker threads take chunks from a queue, each with its own HTTP Range request (the original URL is
asked again for every chunk, so a short-lived redirect link never expires on a long download). A chunk that stalls (no data for
20 s) or fails is retried, so one slow connection cannot hold the whole download back. Finished chunks are recorded next to the file
(<file>.parts), so an interrupted download resumes where it stopped.

Usage: python fastdl.py URL DEST EXPECTED_SIZE [connections]
Only the Python standard library is used.
"""
import os
import queue
import sys
import threading
import time
import urllib.request

CHUNK = 16 * 1024 * 1024
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) RemixGlassFix-installer'


def fetch_range(url, start, end, timeout=20):
    req = urllib.request.Request(url, headers={'Range': 'bytes=%d-%d' % (start, end), 'User-Agent': UA})
    resp = urllib.request.urlopen(req, timeout=timeout)
    if resp.status not in (200, 206):
        raise IOError('HTTP %s' % resp.status)
    if resp.status == 200 and start != 0:
        raise IOError('server ignored the Range request')
    return resp


def main():
    url, dest, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
    conns = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    parts_file = dest + '.parts'
    n_chunks = (size + CHUNK - 1) // CHUNK
    done = set()
    if os.path.isfile(dest) and os.path.getsize(dest) == size and os.path.isfile(parts_file):
        done = set(int(x) for x in open(parts_file).read().split())
    elif os.path.isfile(dest) and os.path.getsize(dest) == size and not os.path.isfile(parts_file):
        print('already downloaded')
        return
    else:
        with open(dest, 'wb') as f:
            f.truncate(size)
        open(parts_file, 'w').close()
    todo = queue.Queue()
    for i in range(n_chunks):
        if i not in done:
            todo.put(i)
    lock = threading.Lock()
    state = {'bytes': sum(min(CHUNK, size - i * CHUNK) for i in done), 'failed': False, 'last': time.time()}
    start_bytes = state['bytes']
    t0 = time.time()

    def worker():
        with open(dest, 'r+b') as out:
            while not state['failed']:
                try:
                    i = todo.get_nowait()
                except queue.Empty:
                    return
                a = i * CHUNK
                b = min(a + CHUNK, size) - 1
                for attempt in range(1, 7):
                    counted = 0
                    try:
                        resp = fetch_range(url, a, b)
                        pos = a
                        while pos <= b:
                            data = resp.read(min(1 << 20, b - pos + 1))
                            if not data:
                                raise IOError('connection closed early')
                            out.seek(pos)
                            out.write(data)
                            pos += len(data)
                            counted += len(data)
                            with lock:
                                state['bytes'] += len(data)
                        with lock:
                            with open(parts_file, 'a') as pf:
                                pf.write('%d\n' % i)
                        break
                    except Exception as e:  # stall, reset, bad status: take the chunk again
                        # bytes already counted for the failed attempt are taken back
                        with lock:
                            state['bytes'] -= counted
                        if attempt == 6:
                            with lock:
                                state['failed'] = True
                            print('\nchunk %d failed: %r' % (i, e), flush=True)
                            return
                        time.sleep(min(2 * attempt, 8))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(conns)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(1)
        with lock:
            got = state['bytes']
        rate = (got - start_bytes) / max(time.time() - t0, 0.1) / 1e6
        print('\r  %5.1f%%  %7.1f / %.1f MB  %5.1f MB/s   ' % (100.0 * got / size, got / 1e6, size / 1e6, rate), end='', flush=True)
    print()
    if state['failed']:
        sys.exit('download did not finish; run it again, it resumes')
    done_n = len(set(int(x) for x in open(parts_file).read().split()))
    if done_n != n_chunks:
        sys.exit('download incomplete (%d of %d chunks); run it again' % (done_n, n_chunks))
    os.remove(parts_file)
    print('done: %s (%d bytes)' % (dest, os.path.getsize(dest)))


if __name__ == '__main__':
    main()

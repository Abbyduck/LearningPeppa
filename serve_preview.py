"""Loopback-only static preview server with HTTP byte ranges for video seeking."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        self.byte_range = None
        path = Path(self.translate_path(self.path))
        request = self.headers.get('Range')
        if not request or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        m = re.fullmatch(r'bytes=(\d*)-(\d*)', request.strip())
        if not m or not (m[1] or m[2]):
            self.send_error(416, 'Invalid byte range')
            return None
        if m[1]:
            start, end = int(m[1]), min(int(m[2]) if m[2] else size-1, size-1)
        else:
            start, end = max(0, size-int(m[2])), size-1
        if start < 0 or start >= size or end < start:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        f = path.open('rb')
        f.seek(start)
        self.byte_range = (start, end)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end-start+1))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        try:
            if self.byte_range is None:
                return super().copyfile(source, outputfile)
            remaining = self.byte_range[1]-self.byte_range[0]+1
            while remaining:
                data = source.read(min(65536, remaining))
                if not data:
                    break
                outputfile.write(data)
                remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Normal when a browser seeks and cancels the previous request.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--directory', type=Path, default=Path(__file__).parent/'output'/'forced_alignment'/'S01E01')
    args = parser.parse_args()
    handler = partial(RangeHandler, directory=str(args.directory.resolve()))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'Preview: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

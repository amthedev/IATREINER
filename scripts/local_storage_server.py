from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class PutFileHandler(SimpleHTTPRequestHandler):
    def do_PUT(self) -> None:
        target = self.translate_path(self.path)
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        length = int(self.headers.get("Content-Length") or 0)
        with target_path.open("wb") as handle:
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local GET/PUT file server for IATREINER artifacts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--directory", default="local_storage")
    args = parser.parse_args()

    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    handler = lambda *handler_args, **kwargs: PutFileHandler(  # noqa: E731
        *handler_args,
        directory=str(directory),
        **kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {directory} at http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

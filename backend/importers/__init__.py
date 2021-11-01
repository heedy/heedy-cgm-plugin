from multiprocessing import Process, Queue
from heedy import Plugin, App
from asyncio import Lock
from .xdrip import xdrip_import
import logging
import os


class Importer:
    importers = {"xdrip": xdrip_import}
    log = logging.getLogger("cgm.importer")

    def __init__(self, p: Plugin, max_process_count: int = 2):
        self.p = p
        self.processes = []
        self.queue = Queue()
        self.max_process_count = max_process_count

    def process_count(self) -> int:
        proc = []
        for p in self.processes:
            if p.is_alive():
                proc.append(p)
        self.processes = proc
        return len(self.processes)

    def start(self):
        pc = self.process_count()
        if pc < self.max_process_count and self.queue.qsize() > 0:
            p = Process(target=self.run)
            self.processes.append(p)
            p.daemon = True
            p.start()

    async def upload(self, app: App, data_type: str, **kwargs):
        self.log.debug("App %s import %s %s", app["id"], data_type, kwargs)
        if not data_type in self.importers:
            raise Exception("Data type not found")

        await app.notify(
            "importer",
            f"{kwargs['filename']} queued for Import ({data_type})",
            description="",
            type="info",
        )

        self.queue.put((app["id"], data_type, kwargs))
        self.start()

    def run(self):
        self.log.debug("Started import process")
        p = Plugin(config=self.p.config, session="sync")

        while self.queue.qsize() > 0:
            app_id, data_type, kwargs = self.queue.get()
            l = self.log.getChild(app_id + "." + data_type)
            l.debug("Importing %s", kwargs)
            app = p.apps[app_id]
            app.notify("importer", f"Importing {kwargs['filename']} ({data_type})...")

            try:
                self.importers[data_type](app, l, **kwargs)
            except Exception as e:
                self.log.error(e)
                app.notify(
                    "importer",
                    f"Failed to upload {kwargs['filename']} ({data_type})",
                    **{
                        "type": "error",
                        "global": True,
                        "description": f"```\n{str(e)}\n```",
                        "seen": False,
                    },
                )
            else:
                app.notify(
                    "importer",
                    f"{kwargs['filename']} imported successfully ({data_type})",
                    description="",
                    type="success",
                    seen=False,
                    _global=True,
                )
            # After import is done, delete the temp file
            os.remove(kwargs["tmpfile"])

        self.log.debug("Stopping import process")

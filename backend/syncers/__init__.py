import asyncio
import logging

from heedy import App
from .nightscout import sync_nightscout


class Syncer:
    active = {}
    alock = asyncio.Lock()
    syncers = {"nightscout": sync_nightscout}

    @staticmethod
    async def sync(app: App):
        appid = app["id"]
        async with Syncer.alock:
            if not appid in Syncer.active:
                Syncer.active[appid] = Syncer(app)
            cursyncer = Syncer.active[appid]
            if cursyncer.task is not None and not cursyncer.task.done():
                cursyncer.l.info("Sync already in progress - not starting a new one")
                return
            cursyncer.task = asyncio.create_task(cursyncer.run_sync())

    def __init__(self, app):
        self.app = app
        self.appid = app["id"]
        self.l = logging.getLogger(f"syncer.{self.appid}")
        self.task = None

    async def run_sync(self):
        try:
            self.l.info("Starting sync")

            # First, get the app's settings
            settings = await self.app.settings

            services = settings["sync_services"]

            if len(services) == 0:
                self.l.info("No sync services configured")
                await self.app.notifications.delete("syncer")
                return

            for service in services:
                stype = service["service_type"]
                self.l.info(f"Syncing {stype}")
                try:
                    await Syncer.syncers[stype](
                        self.app, self.l.getChild(stype), service
                    )
                except Exception as e:
                    self.l.error(f"Error in sync {stype}: {e}")
                    await self.app.notify(
                        "syncer",
                        f"CGM: Sync Failed ({stype})",
                        type="error",
                        _global=True,
                        description=f"```\n{str(e)}\n```",
                        seen=False,
                    )
                    return

            await self.app.notifications.delete("syncer")
        except Exception as e:
            self.l.error(f"Error in sync: {e}")
            await self.app.notify(
                "syncer",
                "CGM: Sync Failed",
                type="error",
                _global=True,
                description=f"```\n{str(e)}\n```",
                seen=False,
            )

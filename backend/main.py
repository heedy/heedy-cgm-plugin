from sqlite3.dbapi2 import Time
from aiohttp import web
from heedy import Plugin, Timeseries
import asyncio
import tempfile
import zipfile
import json
import logging
import tempfile
import shutil
import os

logging.basicConfig(level=logging.DEBUG)

routes = web.RouteTableDef()

# When starting the plugin server, heedy will send initialization data on STDIN.
# The Plugin object reads this data, and connects with Heedy.
p = Plugin()


from importers import Importer
from syncers import Syncer

importer = Importer(p)

# The temporary directory used for storing uploads
tempdir = None

l = logging.getLogger("cgm")


async def validate_request(request):
    if not p.isUser(request):
        raise Exception("Only users allowed")
    app = await p.apps[request.match_info["appid"]]

    username = request.headers["X-Heedy-As"]
    if username != "heedy" and app["owner"] != username:
        raise Exception("User not owner of app")

    if app["plugin"] != f"{p.name}:cgm":
        raise Exception("App not CGM")

    return app


@routes.post("/api/cgm/{appid}/sync")
async def sync(request):
    try:
        app = await validate_request(request)
    except:
        return web.json_response(
            {"error": "not_found", "error_description": "App not found"}, status=403
        )
    l.debug("Sync request for %s", app["id"])
    await app.notify(
        "syncer",
        "CGM: Syncing...",
        type="info",
        _global=False,
        description="",
        seen=False,
    )
    await Syncer.sync(app)
    # data = await request.json()
    # l.debug(data)
    return web.json_response({"result": "ok"})


@routes.post("/api/cgm/{appid}/import")
async def import_data(request):
    try:
        app = await validate_request(request)
    except:
        return web.json_response(
            {"error": "not_found", "error_description": "App not found"}, status=403
        )

    l.debug("Data import request")
    reader = await request.multipart()

    field = await reader.next()
    data = {"data_type": "xdrip"}
    while field is not None:
        if field.name == "data_type":
            data_type = await field.text()
            if data_type not in importer.importers:
                return web.json_response(
                    {
                        "error": "bad_request",
                        "error_description": "Unknown upload type",
                    },
                    status=400,
                )
            data["data_type"] = data_type
        elif field.name == "overwrite":
            ovr = await field.text()
            if ovr not in ["true", "false"]:
                return web.json_response(
                    {
                        "error": "bad_request",
                        "error_description": "Overwrite was not a boolean",
                    },
                    status=400,
                )
            data["overwrite"] = ovr == "true"
        elif field.name == "data":
            filename = field.filename

            global tempdir
            if tempdir is None:
                tempdir = tempfile.mkdtemp(prefix="heedy_cgm_")
                l.debug(f"Created tempdir {tempdir}")

            tfname = tempfile.mktemp(dir=tempdir, suffix=os.path.splitext(filename)[1])
            tf = open(tfname, "wb")

            try:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    tf.write(chunk)
            except:
                tf.close()
                os.remove(tfname)
                raise
            else:
                tf.close()
                data["filename"] = filename
                data["tmpfile"] = tfname
        else:
            return web.json_response(
                {
                    "error": "bad_request",
                    "error_description": "Unrecognized field",
                },
                status=400,
            )
        field = await reader.next()

    if tf is None:
        return web.json_response(
            {
                "error": "bad_request",
                "error_description": "No file was uploaded",
            },
            status=400,
        )

    try:
        await importer.upload(app, **data)
    except Exception as e:
        return web.json_response(
            {
                "error": "bad_request",
                "error_description": str(e),
            },
            status=400,
        )

    return web.json_response({"result": "ok"})


@routes.post("/create")
async def create(request):
    evt = await request.json()

    try:
        app = await p.apps[evt["app"]]
    except:
        # There is a bug in heedy that isn't easy to fix, sometimes the database doesn't yet show the write on first
        # create
        await asyncio.sleep(0.1)
        app = await p.apps[evt["app"]]

    await app.notify(
        "cgm",
        "CGM",
        dismissible=False,
        type="toolbar",
        actions=[
            {
                "href": f"/api/cgm/{evt['app']}/import",
                "title": "Import Data",
                "type": "post/form-data",
                "form_schema": {
                    "data_type": {
                        "type": "string",
                        "title": "Import Data Format",
                        "oneOf": [
                            {"const": "xdrip", "title": "XDrip+ Database Export"}
                        ],
                        "default": "xdrip",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "title": "Import Old Data (Overwrite on Conflict)",
                        "description": "If set, the entire dataset will be inserted, overwriting any datapoints that have identical timestamps. If not, only data that is newer than existing datapoints will be appended.",
                    },
                    "data": {
                        "type": "object",
                        "title": "Choose a Zip File",
                        "description": "A zip file containing exported data in the chosen upload data format.",
                        "contentMediaType": "application/zip",
                        "writeOnly": True,
                    },
                    "required": ["data_type", "data"],
                },
                "description": """# Upload Data
You can upload data exported from a supported service directly into heedy. Currently, the following are available:

- [XDrip+](https://github.com/jamorham/xDrip-plus) - click on `... > Import/Export Features > Export Database`, and upload the resulting zip file here.
""",
            },
            {
                "href": f"/api/cgm/{evt['app']}/sync",
                "title": "Sync Now",
                "type": "post",
            },
        ],
    )

    return web.Response(text="ok")


@routes.post("/settings_update")
async def settings_update(request):
    evt = await request.json()
    l.debug("Settings update: %s", evt)

    return web.Response(text="ok")


async def cleanup(app):
    l.debug("Cleaning up")
    global tempdir
    if tempdir is not None:
        shutil.rmtree(tempdir)
        tempdir = None
    await p.session.close()


async def sync_all():
    l.debug("Starting sync of all CGM services")
    applist = await p.apps(plugin=f"{p.name}:{p.name}")
    for a in applist:
        if len(a["settings"]["sync_services"]) > 0:
            await Syncer.sync(a)


async def sync_loop():
    l.debug("Waiting 14 seconds before first sync")
    await asyncio.sleep(14)
    while True:
        try:
            await sync_all()
        except Exception as e:
            l.error(e)

        wait_until = p.config["config"]["plugin"][p.name]["config"]["sync_every"]
        l.debug(f"Waiting {wait_until} seconds until next auto-sync initiated")
        await asyncio.sleep(wait_until)


async def startup(app):
    asyncio.create_task(sync_loop())


# Runs the plugin's backend server
app = web.Application()
app.add_routes(routes)
app.on_startup.append(startup)
app.on_shutdown.append(cleanup)
web.run_app(app, path=f"{p.name}.sock")

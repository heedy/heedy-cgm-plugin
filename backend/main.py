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

importer = Importer(p)

# The temporary directory used for storing uploads
tempdir = None

l = logging.getLogger("cgm")


@routes.post("/api/cgm/{appid}/upload")
async def upload_data(request):
    if not p.isUser(request):
        return web.json_response(
            {
                "error_description": "You must be a user to access this resource",
                "error": "access_denied",
            },
            status=403,
        )
    try:
        app = await p.apps[request.match_info["appid"]]

        username = request.headers["X-Heedy-As"]
        if username != "heedy" and app["owner"] != username:
            raise Exception("User not owner of app")

        if app["plugin"] != f"{p.name}:cgm":
            raise Exception("App not CGM")

    except:
        return web.json_response(
            {"error": "not_found", "error_description": "App not found"}, status=400
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
        "CGM App Actions",
        dismissible=False,
        actions=[
            {
                "href": f"/api/cgm/{evt['app']}/upload",
                "title": "Upload Data",
                "type": "post/form-data",
                "form_schema": {
                    "data_type": {
                        "type": "string",
                        "title": "Upload Data Format",
                        "oneOf": [
                            {"const": "xdrip", "title": "XDrip+ Database Export"}
                        ],
                        "default": "xdrip",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                        "title": "Overwrite Existing Data",
                        "description": "If set, the uploaded data will replace whatever is in heedy at the time ranges. If not, only data that is newer than existing datapoints will be appended.",
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
            }
        ],
    )
    return web.Response(text="ok")


async def cleanup(app):
    l.debug("Cleaning up")
    global tempdir
    if tempdir is not None:
        shutil.rmtree(tempdir)
        tempdir = None


# Runs the plugin's backend server
app = web.Application()
app.add_routes(routes)
app.on_shutdown.append(cleanup)
web.run_app(app, path=f"{p.name}.sock")

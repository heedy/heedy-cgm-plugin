from typing import Callable
from heedy import App, Timeseries
import logging
import asyncio
from aiohttp import ClientSession
from datetime import datetime
import time


async def get_ns_start_time(s: ClientSession, url: str, l: logging.Logger):
    # There is no data in the timeseries, so we need to find the start time
    # of the dataset in Nightscout
    # We will go by years backwards until there is no more data before that year
    # https://github.com/nightscout/cgm-remote-monitor/issues/5091
    year = datetime.now().year
    while year > 1980:
        l.debug("Checking Nightscout for data before year %d", year)
        async with s.get(
            url,
            params={
                "count": 1,
                "find[dateString][$lte]": f"{year}-01-01",
            },
        ) as r:
            data = await r.json()
            l.info(data)
            if len(data) == 0:
                return datetime.strptime(f"{year}-01-01", "%Y-%m-%d").timestamp()
        year -= 1
    raise Exception(
        "Nightscout holds data from before 1980 - this is unlikely to be valid data, so not syncing."
    )


async def upload_data(
    ts: Timeseries,
    s: ClientSession,
    url: str,
    l: logging.Logger,
    key: str,
):
    l.debug("Syncing %s", url)
    sync_time_key = f"nightscout_sync_time.{url}"
    start_time = await ts.kv[sync_time_key]
    if start_time is None:  # If we haven't synced yet, get nightscout data start time
        l.debug(
            "This server has not synced to this timeseries - checking when Nightscout's dataset starts"
        )
        start_time = await get_ns_start_time(s, url, l)
    l.debug("Start sync time is %s", start_time)
    start_time -= (
        60 * 60 * 24
    )  # amount of time before start time to look for data (1 day)

    current_time = time.time()
    one_year = 60 * 60 * 24 * 365
    while start_time < current_time - one_year:
        end_time = start_time + one_year
        l.debug("Syncing from %s to %s", start_time, end_time)
        async with s.get(
            url,
            params={
                "count": 1000000,  # A year has 525600 minutes, so a million should be more than enough
                "find[date][$lte]": int(end_time * 1000),
                "find[date][$gt]": int(start_time * 1000),
            },
        ) as r:
            data = await r.json()
        if len(data) > 0:
            data = sorted(data, key=lambda x: x["date"])
            l.debug(
                "Got %d datapoints between %s %s",
                len(data),
                data[0]["dateString"],
                data[-1]["dateString"],
            )
            data = list(map(lambda x: {"t": x["date"] / 1000, "d": x[key]}, data))
            await ts.insert_array(data)
            await ts.kv.update(**{sync_time_key: data[-1]["t"]})

        start_time = end_time
    l.debug("Syncing from %s to now", start_time)
    async with s.get(
        url,
        params={
            "count": 1000000,
            "find[date][$gt]": int(start_time * 1000),
        },
    ) as r:
        data = await r.json()
    data = sorted(data, key=lambda x: x["date"])
    if len(data) > 0:
        l.debug(
            "Got %d datapoints between %s %s",
            len(data),
            data[0]["dateString"],
            data[-1]["dateString"],
        )
        data = list(map(lambda x: {"t": x["date"] / 1000, "d": x[key]}, data))
        await ts.insert_array(data)
        await ts.kv.update(**{sync_time_key: data[-1]["t"]})


async def sync_nightscout(app: App, l: logging.Logger, settings: dict):
    url = settings["url"]
    if url.endswith("/"):
        url = url[:-1]
    url = url + "/api/v1"
    l.debug("Syncing to %s", url)
    async with ClientSession(headers={"API-SECRET": settings["api_key"]}) as s:

        # First, get the timeseries of sensor glucose
        sgv = (await app.objects(key="cgm"))[0]
        sgv_url = url + "/entries/sgv.json"
        await upload_data(sgv, s, sgv_url, l, "sgv")

        # First, get the timeseries of manual blood glucose
        mbg = (await app.objects(key="blood_test"))[0]
        mbg_url = url + "/entries/mbg.json"
        await upload_data(mbg, s, mbg_url, l, "mbg")

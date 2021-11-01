from heedy import App
import logging
import zipfile
import os
import shutil
import sqlite3


def xdrip_import(
    app: App,
    l: logging.Logger,
    filename: str = "",
    tmpfile: str = "",
    overwrite: bool = False,
):

    l.debug("Importing xdrip from %s (%s)", filename, tmpfile)

    extract_folder = os.path.splitext(tmpfile)[0]

    try:

        with zipfile.ZipFile(tmpfile, "r") as z:
            zip_info = z.infolist()
            if len(zip_info) != 1:
                raise Exception(
                    "Zip file contains more than one file, an xdrip database export is expected."
                )
            if not zip_info[0].filename.endswith(".sqlite"):
                raise Exception(
                    "Zip file does not contain an sqlite xdrip database export"
                )

            os.mkdir(extract_folder)
            z.extract(zip_info[0], extract_folder)

            db_file = os.path.join(extract_folder, zip_info[0].filename)

        # Get CGM glucose data
        cgm_readings = app.objects(type="timeseries", key="cgm")[0]

        start_timestamp = 0
        if not overwrite and len(cgm_readings) > 0:
            start_timestamp = cgm_readings[-1]["t"]
            l.debug("Importing cgm from %s", start_timestamp)

        db = sqlite3.connect(db_file)
        c = db.cursor()

        batch_size = 100000

        c.execute(
            "SELECT timestamp,AVG(calculated_value) FROM BgReadings WHERE timestamp > ? AND calculated_value > 0 GROUP BY timestamp ORDER BY timestamp ASC;",
            (start_timestamp * 1000,),
        )

        data = c.fetchmany(batch_size)
        while data is not None and len(data) > 0:
            l.debug("Writing cgm batch with %d datapoints", len(data))
            data = list(map(lambda x: {"t": x[0] / 1000, "d": x[1]}, data))
            cgm_readings.insert_array(data)
            data = c.fetchmany(batch_size)

        # Get finger-stick glucose data
        blood_test_readings = app.objects(type="timeseries", key="blood_test")[0]
        start_timestamp = 0
        if not overwrite and len(blood_test_readings) > 0:
            start_timestamp = blood_test_readings[-1]["t"]
            l.debug("Importing blood_test from %s", start_timestamp)

        c.execute(
            "SELECT timestamp,AVG(mgdl) FROM BloodTest WHERE timestamp > ? AND mgdl > 0 GROUP BY timestamp ORDER BY timestamp ASC;",
            (start_timestamp * 1000,),
        )

        data = c.fetchmany(batch_size)
        while data is not None and len(data) > 0:
            l.debug("Writing blood_test batch with %d datapoints", len(data))
            data = list(map(lambda x: {"t": x[0] / 1000, "d": x[1]}, data))
            blood_test_readings.insert_array(data)
            data = c.fetchmany(batch_size)

        # Finally, extract sensor start and stop times
        cgm_events = app.objects(type="timeseries", key="events")[0]
        start_timestamp = 0
        if not overwrite and len(cgm_events) > 0:
            start_timestamp = cgm_events[-1]["t"]
            l.debug("Importing cgm_events from %s", start_timestamp)

        c.execute(
            "SELECT started_at FROM Sensors WHERE started_at > ?",
            (start_timestamp * 1000,),
        )

        data = c.fetchmany(batch_size)
        while data is not None and len(data) > 0:
            l.debug("Writing cgm_events batch with %d datapoints", len(data))
            data = list(map(lambda x: {"t": x[0] / 1000, "d": "sensor_start"}, data))
            cgm_events.insert_array(data)
            data = c.fetchmany(batch_size)

        db.close()

        shutil.rmtree(extract_folder)
    except:
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
        raise

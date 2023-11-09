import os
import sqlite3
import logging
import json
from pathlib import Path
import contextlib

from kicad_nextpcb_new.helpers import (
    natural_sort_collation,
)

class ImportBOMStore:

    def __init__(self, parent):
        self.logger = logging.getLogger(__name__)
        self.parent = parent
        # self.project_path = project_path
        self.project_path ="C:\\Users\\ws\\Desktop\\kicad-nextpcb-tools"
        self.datadir = os.path.join(self.project_path, "nextpcb")
        self.dbfile = os.path.join(self.datadir, "importBOM.db")
        self.order_by = "reference"
        self.order_dir = "ASC"
        self.setup()

    def setup(self):
        """Check if folders and database exist, setup if not"""
        if not os.path.isdir(self.datadir):
            self.logger.info(
                "Data directory 'nextpcb' does not exist and will be created."
            )
            Path(self.datadir).mkdir(parents=True, exist_ok=True)
        self.create_import_db()


    def create_import_db(self):
        """Create the sqlite database tables."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS import_BOM ('reference' ,'value',\
                    'footprint','mpn', 'manufacturer', 'description', 'quantity','part_detail')"
                )
                cur.commit()

    def read_all(self):
        """Read all parts from the database."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            con.create_collation("naturalsort", natural_sort_collation)
            with con as cur:
                return [
                    list(part)
                    for part in cur.execute(
                       f"SELECT reference, value, footprint,  mpn, manufacturer, description, 1 as quantity\
                            FROM import_BOM ORDER BY {self.order_by} COLLATE naturalsort {self.order_dir}"
                    ).fetchall()
                ]

    

    def clear_database(self):
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    f"DELETE FROM import_BOM"
                )
                cur.commit()


    def import_mappings_data(self, Reference_data):
        """Insert to import data into the database."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute("INSERT INTO import_BOM VALUES (?,?,?,?,?,?,?,'' )", 
                                Reference_data)
                cur.commit()


    def set_reference(self, ref, value):
        """Change the BOM attribute for a part in the database."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    f"UPDATE import_BOM SET mpn = '{value}' WHERE reference = '{ref}'"
                )
                cur.commit()    

    def set_manufacturer(self, ref, value):
        """Change the BOM attribute for a part in the database."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    f"UPDATE import_BOM SET manufacturer = '{value}' WHERE reference = '{ref}'"
                )
                cur.commit()

    def set_description(self, ref, value):
        """Change the BOM attribute for a part in the database."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    f"UPDATE import_BOM SET description = '{value}' WHERE reference = '{ref}'"
                )
                cur.commit()

    def set_part_detail(self, ref, value):
        """Change the BOM attribute for a part in the database."""
        value = json.dumps(value)
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                cur.execute(
                    f"UPDATE import_BOM SET part_detail = '{value}' WHERE reference = '{ref}'"
                )
                cur.commit()

    def get_part_detail(self, ref):
        """Get a part from the database by its reference."""
        with contextlib.closing(sqlite3.connect(self.dbfile)) as con:
            with con as cur:
                return cur.execute(
                    f"SELECT part_detail FROM import_BOM WHERE reference = '{ref}'"
                ).fetchone()[0]
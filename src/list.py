import json
import sys
from itertools import product
from typing import Annotated, Optional

import boto3
import typer
from dep_tools.aws import object_exists
from dep_tools.grids import get_tiles
from dep_tools.namers import S3ItemPath

#python src/list.py --years 2024 --version 0.0.1 --regions FJI

def main(
    years: Annotated[str, typer.Option()],
    version: Annotated[str, typer.Option()],
    regions: Optional[str] = "ALL",
    tile_buffer_kms: Optional[int] = 0.0,
    limit: Optional[str] = None,
    base_product: str = "s2_ls",
    output_bucket: Optional[str] = "dep-public-staging",
    #output_prefix: Optional[str] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    country_codes = None if regions.upper() == "ALL" else regions.split(",")

    tiles = get_tiles(
        country_codes=country_codes, buffer_distance=tile_buffer_kms * 1000
    )

    if limit is not None:
        limit = int(limit)

    
    years = years.split("-")
    if len(years) == 2:
        years = range(int(years[0]), int(years[1]) + 1)
    elif len(years) > 2:
        ValueError(f"{years} is not a valid value for --years")

    tasks = [
        {
            "tile-id": ",".join([str(i) for i in tile[0]]),
            "year": year,
            "version": version,
        }
        for tile, year in product(list(tiles), years)
    ]

    
    
    if limit is not None:
        tasks = tasks[0:limit]

    json.dump(tasks, sys.stdout)


if __name__ == "__main__":
    typer.run(main)

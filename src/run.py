import os
import xarray as xr
import geopandas as gpd

import odc.geo.xr  # noqa: F401

from logging import INFO, Formatter, Logger, StreamHandler, getLogger

import boto3
import dask
import typer

# from dask.distributed import Client
from dask.distributed import Client as DaskClient
from dep_tools.aws import object_exists
from dep_tools.exceptions import EmptyCollectionError
from dep_tools.grids import PACIFIC_GRID_10, PACIFIC_GRID_30
from dep_tools.loaders import OdcLoader
from dep_tools.namers import S3ItemPath
from dep_tools.searchers import PystacSearcher
from dep_tools.stac_utils import StacCreator, set_stac_properties
from dep_tools.task import AwsStacTask as Task
from dep_tools.writers import AwsDsCogWriter, AwsStacWriter, LocalStacWriter, LocalDsCogWriter
from odc.stac import configure_s3_access
from typing_extensions import Annotated, Optional

from dea_tools.dask import create_local_dask_cluster

import dep_tools.grids as grid
import util

# NIU uv run intertidal/run.py --tile-id 77,19 --year 2024 --version 0.0.1
# NRU uv run intertidal/run.py --tile-id 50,41 --year 2024 --version 0.0.1


# Main
def main(
    tile_id: Annotated[str, typer.Option()],
    year: Annotated[str, typer.Option()],
    version: Annotated[str, typer.Option()],
    coastal_buffer:Optional[float] = 0.002, #0.002 - 0.005
    cloud_cover: Optional[str] = "50",
    output_bucket: Optional[str] = "dep-public-staging",
    dataset_id: str = "intertidal",
    base_product: str = "s2ls",
    memory_limit: str = "64GB",
    workers: int = 4,
    threads_per_worker: int = 32,
) -> None:
    log = get_logger(tile_id)
    log.info("Starting processing...")

    # dask and aws
    # client = create_local_dask_cluster(return_client=True)
    client = DaskClient(
        n_workers=workers, threads_per_worker=threads_per_worker, memory_limit=memory_limit
    )
    log.info(client)
    aws_client = boto3.client("s3")
    configure_s3_access(cloud_defaults=True, requester_pays=True)

    # ensure Pacific FES2022 Tide Models
    util.setup_tidal_models()

    # get aoi
    grid = PACIFIC_GRID_30
    tile_index = tuple(int(i) for i in tile_id.split(","))
    aoi = grid.tile_geobox(tile_index)

    #test
    #aoi = gpd.read_file("coral_coast.geojson")

    log.info(f"{tile_id} [{year}]")
    ds_ls, ds_s2 = util.get_s2_ls(aoi=aoi, year=year, cloud_cover=cloud_cover, coastal_buffer=coastal_buffer)
    ndwi = util.get_ndwi(ds_ls, ds_s2)
    ndwi = ndwi.compute()

    #elevation
    ds = util.get_evelation(ndwi)
    
    #exposure
    ds = util.get_exposure(ds, year=year)

    #cleanup
    ds = util.cleanup(ds)

    #write locally
    log.info("Saving Outputs Locally...")
    util.write_locally(ds, tile_id=tile_id, year=year)

    #itempath
    itempath = S3ItemPath(
        bucket=output_bucket,
        sensor=base_product,
        dataset_id=dataset_id,
        version=version,
        time=year,
    )
    
    #write externally
    output_data = set_stac_properties(
        ndwi, ds
    )
    data_writer = AwsDsCogWriter(itempath, write_multithreaded=True)
    #data_writer = LocalDsCogWriter(itempath=itempath)
    paths = data_writer.write(output_data, tile_id)
    
    #stac_writer = AwsStacWriter(itempath)
    stac_writer = LocalStacWriter(itempath)

    
    stac_creator = StacCreator(
        itempath=itempath, remote=True, make_hrefs_https=True, with_raster=True
    )
    stac_item = stac_creator.process(output_data, tile_id)
    #stac_writer.write(stac_item, tile_id)

    #stac_document = itempath.stac_path(tile_id)

    #finish
    log.info(f"{tile_id} - {year} Processed.")
    client.close()
    

# Logger
def get_logger(region_code: str) -> Logger:
    """Set Logger"""
    console = StreamHandler()
    time_format = "%Y-%m-%d %H:%M:%S"
    console.setFormatter(
        Formatter(
            fmt=f"%(asctime)s %(levelname)s ({region_code}):  %(message)s",
            datefmt=time_format,
        )
    )
    log = getLogger("INTERTIDAL")
    log.addHandler(console)
    log.setLevel(INFO)
    return log


# Run
if __name__ == "__main__":
    typer.run(main)

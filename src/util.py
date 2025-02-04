import os
import odc.geo.xr  # noqa: F401
from pathlib import Path
import requests
import re
import urllib
from xarray import Dataset
from geopandas import GeoDataFrame
import geopandas as gpd
import xarray as xr
from intertidal.io import prepare_for_export
from intertidal.elevation import elevation
from intertidal.exposure import exposure
from pystac_client import Client
from odc.stac import load
import rasterio.features
from intertidal.io import prepare_for_export
import json
import pyogrio

catalog = "https://earth-search.aws.element84.com/v1"
landsat_collection = "landsat-c2-l2"
sentinel2_collection = "sentinel-2-l2a"
tide_model = "FES2022"
tide_model_dir = "tidal_models"


def setup_tidal_models() -> None:
    print("Setting Up Pacific FES2022 Tidal Models...")
    #os.environ["PYTHONHTTPSVERIFY"] = "0"
    list_url = "https://dep-public-staging.s3.us-west-2.amazonaws.com/dep_ls_coastlines/raw/tidal_models/fes2022b/tide_data_urls.txt"
    for item_url in requests.get(list_url, stream=True).iter_lines(
        decode_unicode=True
    ):
        local_path = Path(re.sub("^.*(tidal_models.*)$", "\\1", item_url))
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(item_url, local_path)


def get_s2_ls(
    aoi: GeoDataFrame, year="2024", cloud_cover=50, coastal_buffer=0.002
) -> tuple[Dataset, Dataset]:

    #bbox = rasterio.features.bounds(aoi)
    bbox = aoi.to_crs(4326).boundingbox.bbox

    common_options = {
        "chunks": {"x": 2048, "y": 2048},
        "groupby": "solar_day",
        "resampling": {"qa_pixel": "nearest", "SCL": "nearest", "*": "cubic"},
        "fail_on_error": False,
    }

    client = Client.open(catalog)

    # Search for Landsat/S2 items
    ls_items = client.search(
        collections=[landsat_collection],
        bbox=bbox,
        datetime=year,
        query={"eo:cloud_cover": {"lt": cloud_cover}},
    ).item_collection()

    s2_items = client.search(
        collections=[sentinel2_collection],
        bbox=bbox,
        datetime=year,
        query={"eo:cloud_cover": {"lt": cloud_cover}},
    ).item_collection()

    print(f"S2 Items : {len(s2_items)} | LS Items : {len(ls_items)}")
    
    # Load STAC Items
    ls_data = load(
        items=ls_items,
        bbox=bbox,
        bands=["green", "nir08", "qa_pixel"],
        **common_options,
    )

    s2_data = load(
        items=s2_items,
        like=ls_data,
        bands=["green", "nir", "scl"],
        **common_options,
    )

    # Cloud Mask
    bitflags = 0b00011000
    cloud_mask = (ls_data.qa_pixel & bitflags) != 0
    ls_data = ls_data.where(~cloud_mask).drop_vars("qa_pixel")

    mask_flags = [1, 3, 9]
    cloud_mask = ~s2_data.scl.isin(mask_flags)
    s2_data = s2_data.where(cloud_mask).drop_vars("scl")

    # Scale and Offset
    ds_ls = (ls_data.where(ls_data.green != 0) * 0.0000275 + -0.2).clip(0, 1)
    ds_s2 = (s2_data.where(s2_data.green != 0) * 0.0001).clip(0, 1)

    ds_ls = get_buffered_coastlines(ds_ls, coastal_buffer)
    ds_s2 = get_buffered_coastlines(ds_s2, coastal_buffer)

    return ds_ls, ds_s2

def get_buffered_coastlines(ds, buffer) -> GeoDataFrame:
    #coastal buffer
    pyogrio.set_gdal_config_options({"OGR_GEOJSON_MAX_OBJ_SIZE": 0})
    url = f"https://dep-public-staging.s3.us-west-2.amazonaws.com/aoi/country_lines_{str(buffer)}.geojson"
    geojson = f"country_lines_{str(buffer)}.geojson"
    download_if_not_exists(url, geojson)
    buffer = gpd.read_file(geojson)
    buffer = buffer.to_crs(4326)
    ds = ds.rio.clip(buffer.geometry.values, buffer.crs, drop=True, invert=False)
    return ds

def get_ndwi(ds_ls: Dataset, ds_s2: Dataset) -> Dataset:
    # Convert to NDWI
    ndwi_ls = (ds_ls.green - ds_ls.nir08) / (ds_ls.green + ds_ls.nir08)
    ndwi_s2 = (ds_s2.green - ds_s2.nir) / (ds_s2.green + ds_s2.nir)

    # Combine into a single dataset
    data = (
        xr.concat([ndwi_ls, ndwi_s2], dim="time").sortby("time").to_dataset(name="ndwi")
    )

    return data


def get_evelation(ds: Dataset) -> Dataset:
    dse, _ = elevation(
        ds,
        tide_model=tide_model,
        tide_model_dir=tide_model_dir,
    )
    return dse


def get_exposure(ds: Dataset, year) -> Dataset:
    # Exposure variables
    modelled_freq = "3h"  # Frequency to run tidal model e.g '30min' or '1h'
    filters = None  # Exposure filters eg None, ['Dry', 'Neap_low']
    filters_combined = None  # Must be a list of tuples containing one temporal and spatial filter each, eg None or [('Einter','Lowtide')]

    exposure_filters, modelledtides_ds = exposure(
        dem=ds.elevation,
        start_date=f"{year}-01-01",
        end_date=f"{year}-12-31",
        modelled_freq=modelled_freq,
        tide_model=tide_model,
        tide_model_dir=tide_model_dir,
        filters=filters,
        filters_combined=filters_combined,
    )

    # Write each exposure output as new variables in the main dataset
    for x in exposure_filters.data_vars:
        ds[f"exposure_{x}"] = exposure_filters[x]

    return ds


def cleanup(ds: Dataset) -> Dataset:
    ds = ds.drop_vars("qa_count_clear")
    ds = ds.drop_vars("qa_ndwi_corr")
    ds = ds.drop_vars("qa_ndwi_freq")
    ds = ds.drop_vars("elevation_uncertainty")
    ds = ds.rename_vars({"exposure_unfiltered": "exposure"})
    return ds

def write_locally(ds, tile_id, year) -> None:
    output_dir = f"data/{tile_id}/{year}"
    os.makedirs(output_dir, exist_ok=True)
    ds_prepared = prepare_for_export(ds, output_location=output_dir)

def download_if_not_exists(url, filepath):
    #Downloads a JSON file from a URL if it doesn't already exist locally.
    if not os.path.exists(filepath):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            with open(filepath, mode="wb") as file:
                for chunk in response.iter_content(chunk_size=10 * 1024):
                    file.write(chunk)
            print(f"GeoJSON file downloaded and saved to: {filepath}")
        except requests.exceptions.RequestException as e:
            print(f"Error downloading JSON: {e}")
        except Exception as e:  # Catch other potential errors (like file writing)
            print(f"An unexpected error occurred: {e}")
    else:
        pass
    
import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any
import pandas as pd # type: ignore
import numpy as np # type: ignore
import geopandas as gpd # type: ignore
import rasterio # type: ignore
from rasterstats import zonal_stats # type: ignore
from shapely.geometry import Point # type: ignore
import csv
from datetime import datetime
import xarray as xr # type: ignore

sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils.dataHandling_utils.variable_utils import VariableHandler # type: ignore

class ProjectInitialisation:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.data_dir = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.data_dir / f"domain_{self.domain_name}"

    def setup_project(self):
        self.project_dir.mkdir(parents=True, exist_ok=True)
        
        shapefile_dir = self.project_dir / "shapefiles"
        shapefile_dir.mkdir(parents=True, exist_ok=True)
        pourPoint_dir = shapefile_dir / "pour_point"
        pourPoint_dir.mkdir(parents=True, exist_ok=True)
        catchment_dir = shapefile_dir / "catchment"
        catchment_dir.mkdir(parents=True, exist_ok=True)
        riverNetwork_dir = shapefile_dir / "river_network"
        riverNetwork_dir.mkdir(parents=True, exist_ok=True)
        riverBasins_dir = shapefile_dir / "river_basins"
        riverBasins_dir.mkdir(parents=True, exist_ok=True)
        Q_observations_dir = self.project_dir / 'observations' / 'streamflow' / 'raw_data'
        Q_observations_dir.mkdir(parents=True, exist_ok=True)
        documentation_dir = self.project_dir / "documentation"
        documentation_dir.mkdir(parents=True, exist_ok=True)
        attributes_dir = self.project_dir / 'attributes'
        attributes_dir.mkdir(parents=True, exist_ok=True)

        return self.project_dir

    def create_pourPoint(self):
        if self.config.get('POUR_POINT_COORDS', 'default').lower() == 'default':
            return None
        
        try:
            lat, lon = map(float, self.config['POUR_POINT_COORDS'].split('/'))
            point = Point(lon, lat)
            gdf = gpd.GeoDataFrame({'geometry': [point]}, crs="EPSG:4326")
            
            if self.config.get('POUR_POINT_SHP_PATH') == 'default':
                output_path = self.project_dir / "shapefiles" / "pour_point"
            else:
                output_path = Path(self.config['POUR_POINT_SHP_PATH'])
            
            pour_point_shp_name = self.config.get('POUR_POINT_SHP_NAME')
            if pour_point_shp_name == 'default':
                pour_point_shp_name = f"{self.domain_name}_pourPoint.shp"
            
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / pour_point_shp_name
            
            gdf.to_file(output_file)
            return output_file
        except ValueError:
            self.logger.error("Invalid pour point coordinates format. Expected 'lat,lon'.")
        except Exception as e:
            self.logger.error(f"Error creating pour point shapefile: {str(e)}")
        
        return None


class DataAcquisitionProcessor:
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.root_path = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.root_path / f"domain_{self.domain_name}"
        self.variable_handler = VariableHandler(self.config, self.logger, 'ERA5', 'SUMMA')
        

    def prepare_maf_json(self) -> Path:
        """Prepare the JSON file for the Model Agnostic Framework."""

        met_path = str(self.root_path / "installs/datatool/" / "extract-dataset.sh")
        gis_path = str(self.root_path / "installs/gistool/" / "extract-gis.sh")
        easymore_client = str(self.config.get('EASYMORE_CLIENT'))

        subbasins_name = self.config.get('RIVER_BASINS_NAME')
        if subbasins_name == 'default':
            subbasins_name = f"{self.config['DOMAIN_NAME']}_riverBasins_{self.config['DOMAIN_DEFINITION_METHOD']}.shp"

        tool_cache = self.config.get('TOOL_CACHE')
        if tool_cache == 'default':
            tool_cache = '$HOME/cache_dir/'

        variables = self.config['FORCING_VARIABLES']
        if variables == 'default':
            variables = self.variable_handler.get_dataset_variables(dataset = self.config['FORCING_DATASET'])

        maf_config = {
            "exec": {
                "met": met_path,
                "gis": gis_path,
                "remap": easymore_client
            },
            "args": {
                "met": [{
                    "dataset": self.config.get('FORCING_DATASET'),
                    "dataset-dir": str(Path(self.config.get('DATATOOL_DATASET_ROOT')) / "era5/"),
                    "variable": variables,
                    "output-dir": str(self.project_dir / "forcing/datatool-outputs"),
                    "start-date": f"{self.config.get('EXPERIMENT_TIME_START')}",
                    "end-date": f"{self.config.get('EXPERIMENT_TIME_END')}",
                    "shape-file": str(self.project_dir / "shapefiles/river_basins" / subbasins_name),
                    "prefix": f"domain_{self.domain_name}_",
                    "cache": tool_cache,
                    "account": self.config.get('TOOL_ACCOUNT'),
                    "_flags": [
                        #"submit-job",
                        #"parsable"
                    ]
                }],
                "gis": [
                    {
                        "dataset": "MODIS",
                        "dataset-dir": str(Path(self.config.get('GISTOOL_DATASET_ROOT')) / "MODIS"),
                        "variable": "MCD12Q1.061",
                        "start-date": "2001-01-01",
                        "end-date": "2020-01-01",
                        "output-dir": str(self.project_dir / "attributes/gistool-outputs"),
                        "shape-file": str(self.project_dir / "shapefiles/river_basins" / subbasins_name),
                        "print-geotiff": "true",
                        "stat": ["frac", "majority", "coords"],
                        "lib-path": self.config.get('GISTOOL_LIB_PATH'),
                        "cache": tool_cache,
                        "prefix": f"domain_{self.domain_name}_",
                        "account": self.config.get('TOOL_ACCOUNT'),
                        "fid": self.config.get('RIVER_BASIN_SHP_RM_GRUID'),
                        "_flags": ["include-na", "parsable"]#, "submit-job"]
                    },
                    {
                        "dataset": "soil_class",
                        "dataset-dir": str(Path(self.config.get('GISTOOL_DATASET_ROOT')) / "soil_classes"),
                        "variable": "soil_classes",
                        "output-dir": str(self.project_dir / "attributes/gistool-outputs"),
                        "shape-file": str(self.project_dir / "shapefiles/river_basins" / subbasins_name),
                        "print-geotiff": "true",
                        "stat": ["majority"],
                        "lib-path": self.config.get('GISTOOL_LIB_PATH'),
                        "cache": tool_cache,
                        "prefix": f"domain_{self.domain_name}_",
                        "account": self.config.get('TOOL_ACCOUNT'),
                        "fid": self.config.get('RIVER_BASIN_SHP_RM_GRUID'),
                        "_flags": ["include-na", "parsable"]#, "submit-job"]
                    },
                    {
                        "dataset": "merit-hydro",
                        "dataset-dir": str(Path(self.config.get('GISTOOL_DATASET_ROOT')) / "MERIT-Hydro"),
                        "variable": "elv,hnd",
                        "output-dir": str(self.project_dir / "attributes/gistool-outputs"),
                        "shape-file": str(self.project_dir / "shapefiles/river_basins" / subbasins_name),
                        "print-geotiff": "true",
                        "stat": ["min", "max", "mean", "median"],
                        "lib-path": self.config.get('GISTOOL_LIB_PATH'),
                        "cache": tool_cache,
                        "prefix": f"domain_{self.domain_name}_",
                        "account": self.config.get('TOOL_ACCOUNT'),
                        "fid": self.config.get('RIVER_BASIN_SHP_RM_GRUID'),
                        "_flags": ["include-na", "parsable"]#, "submit-job",]
                    }
                ],
                "remap": [{
                    "case-name": "remapped",
                    "cache": tool_cache,
                    "shapefile": str(self.project_dir / "shapefiles/river_basins" / subbasins_name),
                    "shapefile-id": self.config.get('RIVER_BASIN_SHP_RM_GRUID'),
                    "source-nc": str(self.project_dir / "forcing/datatool-outputs/**/*.nc*"),
                    "variable-lon": "lon",
                    "variable-lat": "lat",
                    "variable": variables,
                    "remapped-var-id": "hruId",
                    "remapped-dim-id": "hru",
                    "output-dir": str(self.project_dir / "forcing/easymore-outputs/") + '/',
                    "job-conf": self.config.get('EASYMORE_JOB_CONF'),
                    #"_flags": ["submit-job"]
                }]
            },
            "order": {
                "met": 1,
                "gis": -1,
                "remap": 2
            }
        }

        # Save the JSON file
        json_path = self.project_dir / "forcing/maf_config.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, 'w') as f:
            json.dump(maf_config, f, indent=2)

        self.logger.info(f"MAF configuration JSON saved to: {json_path}")
        return json_path

    def run_data_acquisition(self):
        """Run the data acquisition process using MAF."""
        json_path = self.prepare_maf_json()
        self.logger.info("Starting data acquisition process")


        maf_script = self.root_path / "installs/MAF/02_model_agnostic_component/model-agnostic.sh"
        
        #Run the MAF script
        try:
            subprocess.run([str(maf_script), str(json_path)], check=True)
            self.logger.info("Model Agnostic Framework completed successfully.")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error running Model Agnostic Framework: {e}")
            raise
        self.logger.info("Data acquisition process completed")
    
    def _get_file_path(self, file_type, file_def_path, file_name):
        """
        Construct file paths based on configuration.

        Args:
            file_type (str): Type of the file (used as a key in config).
            file_def_path (str): Default path relative to project directory.
            file_name (str): Name of the file.

        Returns:
            Path: Constructed file path.
        """
        if self.config.get(f'{file_type}') == 'default':
            return self.project_dir / file_def_path / file_name
        else:
            return Path(self.config.get(f'{file_type}'))

class DataCleanupProcessor:
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.root_path = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.root_path / f"domain_{self.domain_name}"

    def cleanup_and_checks(self):
        """Perform cleanup and checks on the MAF output."""
        self.logger.info("Performing cleanup and checks on MAF output")
        
        # Define paths
        path_soil_type = self.project_dir / f'attributes/soil_class/domain_{self.domain_name}_stats_soil_classes.csv'
        path_landcover_type = self.project_dir / f'attributes/land_class/domain_{self.domain_name}_stats_NA_NALCMS_landcover_2020_30m.csv'
        path_elevation_mean = self.project_dir / f'attributes/elevation/domain_{self.domain_name}_stats_elv.csv'

        # Read files
        soil_type = pd.read_csv(path_soil_type)
        landcover_type = pd.read_csv(path_landcover_type)
        elevation_mean = pd.read_csv(path_elevation_mean)

        # Sort by COMID
        soil_type = soil_type.sort_values(by='COMID').reset_index(drop=True)
        landcover_type = landcover_type.sort_values(by='COMID').reset_index(drop=True)
        elevation_mean = elevation_mean.sort_values(by='COMID').reset_index(drop=True)

        # Check if COMIDs are the same across all files
        if not (len(soil_type) == len(landcover_type) == len(elevation_mean) and
                (soil_type['COMID'] == landcover_type['COMID']).all() and
                (landcover_type['COMID'] == elevation_mean['COMID']).all()):
            raise ValueError("COMIDs are not consistent across soil, landcover, and elevation files")

        # Process soil type
        majority_value = soil_type['majority'].replace(0, np.nan).mode().iloc[0]
        soil_type['majority'] = soil_type['majority'].replace(0, majority_value).fillna(majority_value)
        if self.config.get('UNIFY_SOIL', False):
            soil_type['majority'] = majority_value

        # Process landcover
        min_land_fraction = self.config.get('MINIMUM_LAND_FRACTION', 0.01)
        for col in landcover_type.columns:
            if col.startswith('frac_'):
                landcover_type[col] = landcover_type[col].apply(lambda x: 0 if x < min_land_fraction else x)
        
        for index, row in landcover_type.iterrows():
            frac_columns = [col for col in landcover_type.columns if col.startswith('frac_')]
            row_sum = row[frac_columns].sum()
            if row_sum > 0:
                for col in frac_columns:
                    landcover_type.at[index, col] /= row_sum

        num_land_cover = self.config.get('NUM_LAND_COVER', 20)
        missing_columns = [f"frac_{i}" for i in range(1, num_land_cover+1) if f"frac_{i}" not in landcover_type.columns]
        for col in missing_columns:
            landcover_type[col] = 0

        frac_columns = [col for col in landcover_type.columns if col.startswith('frac_')]
        frac_columns.sort(key=lambda x: int(x.split('_')[1]))
        sorted_columns = [col for col in landcover_type.columns if col not in frac_columns] + frac_columns
        landcover_type = landcover_type.reindex(columns=sorted_columns)

        for col in frac_columns:
            if landcover_type.loc[0, col] < 0.00001:
                landcover_type.loc[0, col] = 0.00001

        # Process elevation
        elevation_mean['mean'].fillna(0, inplace=True)

        # Save modified files
        soil_type.to_csv(self.project_dir / 'attributes/soil_class/modified_domain_stats_soil_classes.csv', index=False)
        landcover_type.to_csv(self.project_dir / 'attributes/land_class/modified_domain_stats_NA_NALCMS_landcover_2020_30m.csv', index=False)
        elevation_mean.to_csv(self.project_dir / 'attributes/elevation/modified_domain_stats_elv.csv', index=False)

        self.logger.info("Cleanup and checks completed")

    

class DataPreProcessor:
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.root_path = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.root_path / f"domain_{self.domain_name}"

    def get_nodata_value(self, raster_path):
        with rasterio.open(raster_path) as src:
            nodata = src.nodatavals[0]
            if nodata is None:
                nodata = -9999
            return nodata

    def calculate_elevation_stats(self):
        self.logger.info("Calculating elevation statistics")
        subbasins_name = self.config.get('CATCHMENT_SHP_NAME')
        if subbasins_name == 'default':
            subbasins_name = f"{self.config['DOMAIN_NAME']}_HRUs_{self.config['DOMAIN_DISCRETIZATION']}.shp"

        catchment_path = self._get_file_path('CATCHMENT_PATH', 'shapefiles/catchment', subbasins_name)

        dem_name = self.config['DEM_NAME']
        if dem_name == "default":
            dem_name = f"domain_{self.config['DOMAIN_NAME']}_elv.tif"

        dem_path = self._get_file_path('DEM_PATH', 'attributes/elevation/dem', dem_name)
        intersect_path = self._get_file_path('INTERSECT_DEM_PATH', 'shapefiles/catchment_intersection/with_dem', self.config.get('INTERSECT_DEM_NAME'))

        # Ensure the directory exists
        os.makedirs(os.path.dirname(intersect_path), exist_ok=True)

        catchment_gdf = gpd.read_file(catchment_path)
        nodata_value = self.get_nodata_value(dem_path)

        with rasterio.open(dem_path) as src:
            affine = src.transform
            dem_data = src.read(1)

        stats = zonal_stats(catchment_gdf, dem_data, affine=affine, stats=['mean'], nodata=nodata_value)
        result_df = pd.DataFrame(stats).rename(columns={'mean': 'elev_mean_new'})
        
        if 'elev_mean' in catchment_gdf.columns:
            catchment_gdf['elev_mean'] = result_df['elev_mean_new']
        else:
            catchment_gdf['elev_mean'] = result_df['elev_mean_new']

        result_df = result_df.drop(columns=['elev_mean_new'])
        catchment_gdf.to_file(intersect_path)

    def calculate_soil_stats(self):
        self.logger.info("Calculating soil statistics")
        subbasins_name = self.config.get('CATCHMENT_SHP_NAME')
        if subbasins_name == 'default':
            subbasins_name = f"{self.config['DOMAIN_NAME']}_HRUs_{self.config['DOMAIN_DISCRETIZATION']}.shp"

        catchment_path = self._get_file_path('CATCHMENT_PATH', 'shapefiles/catchment', subbasins_name)
        soil_name = self.config['SOIL_CLASS_NAME']
        if soil_name == 'default':
            soil_name = f"domain_{self.config['DOMAIN_NAME']}_soil_classes.tif"
        soil_path = self._get_file_path('SOIL_CLASS_PATH', 'attributes/soilclass/', soil_name)
        intersect_path = self._get_file_path('INTERSECT_SOIL_PATH', 'shapefiles/catchment_intersection/with_soilgrids', self.config.get('INTERSECT_SOIL_NAME'))
        self.logger.info(f'processing landclasses: {soil_path}')

        if not intersect_path.exists() or self.config.get('FORCE_RUN_ALL_STEPS') == True:
            intersect_path.parent.mkdir(parents=True, exist_ok=True)

            catchment_gdf = gpd.read_file(catchment_path)
            nodata_value = self.get_nodata_value(soil_path)

            with rasterio.open(soil_path) as src:
                affine = src.transform
                soil_data = src.read(1)

            stats = zonal_stats(catchment_gdf, soil_data, affine=affine, stats=['count'], categorical=True, nodata=nodata_value)
            result_df = pd.DataFrame(stats)
            
            # Find the most common soil class (excluding 'count' column)
            soil_columns = [col for col in result_df.columns if col != 'count']
            most_common_soil = result_df[soil_columns].sum().idxmax()
            
            # Fill NaN values with the most common soil class (fallback in case very small HRUs)
            if result_df.isna().any().any():
                self.logger.warning("NaN values found in soil statistics. Filling with most common soil class. Please check HRU's size or use higher resolution land class raster")
                result_df = result_df.fillna({col: (0 if col == 'count' else most_common_soil) for col in result_df.columns})            

            def rename_column(x):
                if x == 'count':
                    return x
                try:
                    return f'USDA_{int(float(x))}'
                except ValueError:
                    return x

            result_df = result_df.rename(columns=rename_column)
            result_df = result_df.astype({col: int for col in result_df.columns if col != 'count'})

            # Merge with original GeoDataFrame
            for col in result_df.columns:
                if col != 'count':
                    catchment_gdf[col] = result_df[col]

            try:
                catchment_gdf.to_file(intersect_path)
                self.logger.info(f"Soil statistics calculated and saved to {intersect_path}")
            except Exception as e:
                self.logger.error(f"Failed to save file: {e}")
                raise


    def calculate_land_stats(self):
        self.logger.info("Calculating land statistics")
        subbasins_name = self.config.get('CATCHMENT_SHP_NAME')
        if subbasins_name == 'default':
            subbasins_name = f"{self.config['DOMAIN_NAME']}_HRUs_{self.config['DOMAIN_DISCRETIZATION']}.shp"

        catchment_path = self._get_file_path('CATCHMENT_PATH', 'shapefiles/catchment', subbasins_name)
        land_name = self.config['LAND_CLASS_NAME']
        if land_name == 'default':
            land_name = f"domain_{self.config['DOMAIN_NAME']}_land_classes.tif"
        land_path = self._get_file_path('LAND_CLASS_PATH', 'attributes/landclass/', land_name)
        intersect_path = self._get_file_path('INTERSECT_LAND_PATH', 'shapefiles/catchment_intersection/with_landclass', self.config.get('INTERSECT_LAND_NAME'))
        self.logger.info(f'processing landclasses: {land_path}')

        if not intersect_path.exists() or self.config.get('FORCE_RUN_ALL_STEPS') == True:
            intersect_path.parent.mkdir(parents=True, exist_ok=True)

            catchment_gdf = gpd.read_file(catchment_path)
            nodata_value = self.get_nodata_value(land_path)

            with rasterio.open(land_path) as src:
                affine = src.transform
                land_data = src.read(1)

            stats = zonal_stats(catchment_gdf, land_data, affine=affine, stats=['count'], categorical=True, nodata=nodata_value)
            result_df = pd.DataFrame(stats)
            
            # Find the most common land class (excluding 'count' column)
            land_columns = [col for col in result_df.columns if col != 'count']
            most_common_land = result_df[land_columns].sum().idxmax()
            
            # Fill NaN values with the most common land class (fallback in case very small HRUs)
            if result_df.isna().any().any():
                self.logger.warning("NaN values found in land statistics. Filling with most common land class. Please check HRU's size or use higher resolution land class raster")
                result_df = result_df.fillna({col: (0 if col == 'count' else most_common_land) for col in result_df.columns})

            def rename_column(x):
                if x == 'count':
                    return x
                try:
                    return f'IGBP_{int(float(x))}'
                except ValueError:
                    return x

            result_df = result_df.rename(columns=rename_column)
            result_df = result_df.astype({col: int for col in result_df.columns if col != 'count'})

            # Merge with original GeoDataFrame
            for col in result_df.columns:
                if col != 'count':
                    catchment_gdf[col] = result_df[col]

            try:
                catchment_gdf.to_file(intersect_path)
                self.logger.info(f"Land statistics calculated and saved to {intersect_path}")
            except Exception as e:
                self.logger.error(f"Failed to save file: {e}")
                raise

    def process_zonal_statistics(self):
        self.calculate_elevation_stats()
        self.calculate_soil_stats()
        self.calculate_land_stats()
        self.logger.info("All zonal statistics processed")

    def _get_file_path(self, file_type, file_def_path, file_name):
        if self.config.get(f'{file_type}') == 'default':
            return self.project_dir / file_def_path / file_name
        else:
            return Path(self.config.get(f'{file_type}'))
        
class ObservedDataProcessor:
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.data_dir = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.data_dir / f"domain_{self.domain_name}"
        self.forcing_time_step_size = int(self.config.get('FORCING_TIME_STEP_SIZE'))
        self.data_provider = self.config.get('STREAMFLOW_DATA_PROVIDER', 'USGS').upper()

        self.streamflow_raw_path = self._get_file_path('STREAMFLOW_RAW_PATH', 'observations/streamflow/raw_data', '')
        self.streamflow_processed_path = self._get_file_path('STREAMFLOW_PROCESSED_PATH', 'observations/streamflow/preprocessed', '')
        self.streamflow_raw_name = self.config.get('STREAMFLOW_RAW_NAME')

    def _get_file_path(self, file_type, file_def_path, file_name):
        if self.config.get(f'{file_type}') == 'default':
            return self.project_dir / file_def_path / file_name
        else:
            return Path(self.config.get(f'{file_type}'))

    def get_resample_freq(self):
        if self.forcing_time_step_size == 3600:
            return 'h'
        if self.forcing_time_step_size == 10800:
            return 'h'
        elif self.forcing_time_step_size == 86400:
            return 'D'
        else:
            return f'{self.forcing_time_step_size}s'

    def process_streamflow_data(self):
        try:
            if self.data_provider == 'USGS':
                self._process_usgs_data()
            elif self.data_provider == 'WSC':
                self._process_wsc_data()
            elif self.data_provider == 'VI':
                self._process_vi_data()
            else:
                self.logger.error(f"Unsupported streamflow data provider: {self.data_provider}")
                raise ValueError(f"Unsupported streamflow data provider: {self.data_provider}")
        except Exception as e:
            self.logger.error(f'Issue in streamflow data preprocessing: {e}')

    def _process_vi_data(self):
        self.logger.info("Processing VI (Iceland) streamflow data")
        vi_data = pd.read_csv(self.streamflow_raw_path / self.streamflow_raw_name, 
                              sep=';', 
                              header=None, 
                              names=['YYYY', 'MM', 'DD', 'qobs', 'qc_flag'],
                              parse_dates={'datetime': ['YYYY', 'MM', 'DD']},
                              na_values='',
                              skiprows = 1)

        vi_data['discharge_cms'] = pd.to_numeric(vi_data['qobs'], errors='coerce')
        vi_data.set_index('datetime', inplace=True)

        # Filter out data with qc_flag values indicating unreliable measurements
        # Adjust this based on the specific qc_flag values that indicate reliable data
        #reliable_data = vi_data[vi_data['qc_flag'] <= 100]

        self._resample_and_save(vi_data['discharge_cms'])

    def _process_usgs_data(self):
        self.logger.info("Processing USGS streamflow data")
        usgs_data = pd.read_csv(self.streamflow_raw_path / self.streamflow_raw_name, 
                                comment='#', sep='\t', 
                                skiprows=[6],
                                parse_dates=['datetime'],
                                date_format='%Y-%m-%d %H:%M',
                                low_memory=False 
                                )

        usgs_data = usgs_data.loc[1:]
        usgs_data['discharge_cfs'] = pd.to_numeric(usgs_data[usgs_data.columns[4]], errors='coerce')
        usgs_data['discharge_cms'] = usgs_data['discharge_cfs'] * 0.028316847
        usgs_data['datetime'] = pd.to_datetime(usgs_data['datetime'], format='%Y-%m-%d %H:%M', errors='coerce')
        usgs_data = usgs_data.dropna(subset=['datetime'])
        usgs_data.set_index('datetime', inplace=True)

        self._resample_and_save(usgs_data['discharge_cms'])

    def _process_wsc_data(self):
        self.logger.info("Processing WSC streamflow data")
        wsc_data = pd.read_csv(self.streamflow_raw_path / self.streamflow_raw_name, 
                               comment='#', 
                               low_memory=False)

        wsc_data['ISO 8601 UTC'] = pd.to_datetime(wsc_data['ISO 8601 UTC'], format='ISO8601')
        wsc_data.set_index('ISO 8601 UTC', inplace=True)
        wsc_data.index = wsc_data.index.tz_convert('America/Edmonton').tz_localize(None)
        wsc_data['discharge_cms'] = pd.to_numeric(wsc_data['Value'], errors='coerce')

        self._resample_and_save(wsc_data['discharge_cms'])

    def _resample_and_save(self, data):
        resample_freq = self.get_resample_freq()
        resampled_data = data.resample(resample_freq).mean()
        resampled_data = resampled_data.interpolate(method='time', limit=24)

        output_file = self.streamflow_processed_path / f'{self.domain_name}_streamflow_processed.csv'
        data_to_write = [('datetime', 'discharge_cms')] + list(resampled_data.items())
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            for row in data_to_write:
                if isinstance(row[0], datetime):
                    formatted_datetime = row[0].strftime('%Y-%m-%d %H:%M:%S')
                    csv_writer.writerow([formatted_datetime, row[1]])
                else:
                    csv_writer.writerow(row)

        self.logger.info(f"Processed streamflow data saved to: {output_file}")
        self.logger.info(f"Total rows in processed data: {len(resampled_data)}")
        self.logger.info(f"Number of non-null values: {resampled_data.count()}")
        self.logger.info(f"Number of null values: {resampled_data.isnull().sum()}")

class BenchmarkPreprocessor:
    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.project_dir = Path(self.config.get('CONFLUENCE_DATA_DIR')) / f"domain_{self.config.get('DOMAIN_NAME')}"

    def preprocess_benchmark_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Preprocess data for hydrobm benchmarking.
        
        Args:
            start_date (str): Start date for the experiment run period (YYYY-MM-DD).
            end_date (str): End date for the experiment run period (YYYY-MM-DD).
        
        Returns:
            pd.DataFrame: Daily DataFrame with columns:
                - temperature (K)
                - streamflow (m³/s)
                - precipitation (mm/day)
        """
        self.logger.info("Starting benchmark data preprocessing")

        # Load and process data
        streamflow_data = self._load_streamflow_data()
        forcing_data = self._load_forcing_data()
        merged_data = self._merge_data(streamflow_data, forcing_data)
        
        # Ensure daily timestep and correct units
        daily_data = self._process_to_daily(merged_data)
        
        # Filter data for the experiment run period
        filtered_data = daily_data.loc[start_date:end_date]
        
        # Validate data
        self._validate_data(filtered_data)
        
        # Save preprocessed data
        output_path = self.project_dir / 'evaluation'
        output_path.mkdir(exist_ok=True)
        filtered_data.to_csv(output_path / "benchmark_input_data.csv")
        
        return filtered_data

    def _process_to_daily(self, data: pd.DataFrame) -> pd.DataFrame:
        """Aggregate data to daily values with correct units."""
        daily_data = pd.DataFrame()
        
        # Temperature (K): daily mean
        daily_data['temperature'] = data['temperature'].resample('D').mean()
        
        # Streamflow (m³/s): daily mean
        daily_data['streamflow'] = data['streamflow'].resample('D').mean()
        
        # Precipitation: sum to daily totals in mm/day
        # Input is already in mm/hr from _load_forcing_data
        daily_data['precipitation'] = data['precipitation'].resample('D').sum()
        
        return daily_data

    def _validate_data(self, data: pd.DataFrame):
        """Validate data ranges and consistency."""
        # Check for missing values
        missing = data.isnull().sum()
        if missing.any():
            self.logger.warning(f"Missing values detected:\n{missing}")
        
        # Physical range checks
        if (data['temperature'] < 200).any() or (data['temperature'] > 330).any():
            self.logger.warning("Temperature values outside physical range (200-330 K)")
        
        if (data['streamflow'] < 0).any():
            self.logger.warning("Negative streamflow values detected")
        
        if (data['precipitation'] < 0).any():
            self.logger.warning("Negative precipitation values detected")
            
        if (data['precipitation'] > 1000).any():
            self.logger.warning("Extremely high precipitation values (>1000 mm/day) detected")

        # Log data statistics
        self.logger.info(f"Data statistics:\n{data.describe()}")

    def _load_streamflow_data(self) -> pd.DataFrame:
        """Load and basic process streamflow data."""
        streamflow_path = self.project_dir / "observations" / "streamflow" / "preprocessed" / f"{self.config.get('DOMAIN_NAME')}_streamflow_processed.csv"
        data = pd.read_csv(streamflow_path, parse_dates=['datetime'], index_col='datetime')
        return data.rename(columns={'discharge_cms': 'streamflow'})

    def _load_forcing_data(self) -> pd.DataFrame:
        """Load and process forcing data, returning hourly dataframe."""
        forcing_path = self.project_dir / "forcing" / "basin_averaged_data"
        datasets = [xr.open_dataset(f) for f in forcing_path.glob("*.nc")]
        combined_ds = xr.merge(datasets)
        
        # Average across HRUs
        averaged_ds = combined_ds.mean(dim='hru')
        
        # Convert precipitation to mm/hr (assuming input is m/s)
        precip_data = averaged_ds['pptrate'] * 3600  # mm/s to mm/day
        
        # Create DataFrame with temperature and converted precipitation
        forcing_df = pd.DataFrame({
            'temperature': averaged_ds['airtemp'].to_pandas(),
            'precipitation': precip_data.to_pandas()
        })
        
        return forcing_df

    def _merge_data(self, streamflow_data: pd.DataFrame, forcing_data: pd.DataFrame) -> pd.DataFrame:
        """Merge streamflow and forcing data on timestamps."""
        merged_data = pd.merge(streamflow_data, forcing_data, 
                             left_index=True, right_index=True, 
                             how='inner')
        
        # Check data completeness
        expected_records = len(pd.date_range(merged_data.index.min(), 
                                           merged_data.index.max(), 
                                           freq='h'))
        if len(merged_data) != expected_records:
            self.logger.warning(f"Data gaps detected. Expected {expected_records} records, got {len(merged_data)}")
        
        return merged_data
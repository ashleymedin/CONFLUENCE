import os
import sys
from pathlib import Path
import xarray as xr # type: ignore
import pandas as pd # type: ignore
import numpy as np # type: ignore
import geopandas as gpd # type: ignore
import xarray as xr # type: ignore
from typing import Dict, Any, Optional

sys.path.append(str(Path(__file__).resolve().parent.parent))

from utils.configHandling_utils.logging_utils import get_function_logger # type: ignore
from utils.models_utils.summaflow import ( # type: ignore
    write_summa_forcing,
    write_summa_attribute,
    write_summa_paramtrial,
    write_summa_initial_conditions,
    write_summa_filemanager,
    copy_summa_static_files
)

class SummaPreProcessor:
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.project_dir = Path(self.config.get('CONFLUENCE_DATA_DIR')) / f"domain_{self.config.get('DOMAIN_NAME')}"
        self.summa_setup_dir = self.project_dir / "settings" / "summa_setup"
        
        # Add these new attributes
        self.geofabric_mapping = self.config.get('GEOFABRIC_MAPPING', {})
        self.landcover_mapping = self.config.get('LANDCOVER_MAPPING', {})
        self.soil_mapping = self.config.get('SOIL_MAPPING', {})
        self.write_mizuroute_domain = self.config.get('WRITE_MIZUROUTE_DOMAIN', False)

    @get_function_logger
    def run_preprocessing(self):
        self.logger.info("Starting SUMMA preprocessing")
        
        self.summa_setup_dir.mkdir(parents=True, exist_ok=True)
        
        # Write SUMMA attribute file
        attr = self.write_summa_attribute()
        
        # Write SUMMA forcing file
        forcing = self.write_summa_forcing(attr)
        
        # Write SUMMA parameter trial file
        self.write_summa_paramtrial(attr)
        
        # Write SUMMA initial conditions file
        self.write_summa_initial_conditions(attr)
        
        # Write SUMMA file manager
        self.write_summa_filemanager(forcing)
        
        # Copy SUMMA static files
        self.copy_summa_static_files()
        
        self.logger.info("SUMMA preprocessing completed")

    def write_summa_attribute(self):
        subbasins_name = self.config.get('CATCHMENT_SHP_NAME')
        if subbasins_name == 'default':
            subbasins_name = f"{self.config['DOMAIN_NAME']}_HRUs_{self.config['DOMAIN_DISCRETIZATION']}.shp"

        subbasins_shapefile = self.project_dir / "shapefiles" / "catchment" / subbasins_name

        rivers_name = self.config.get('RIVER_NETWORK_SHP_NAME')
        if rivers_name == 'default':
            rivers_name = f"{self.config['DOMAIN_NAME']}_riverNetwork_delineate.shp"

        rivers_shapefile = self.project_dir / "shapefiles" / "river_network" / rivers_name
        gistool_output = self.project_dir / "attributes"
        
        return write_summa_attribute(
            self.summa_setup_dir,
            subbasins_shapefile,
            rivers_shapefile,
            gistool_output,
            self.config.get('MINIMUM_LAND_FRACTION'),
            self.config.get('HRU_DISCRETIZATION'),
            self.geofabric_mapping,
            self.landcover_mapping,
            self.soil_mapping,
            self.write_mizuroute_domain
        )

    def write_summa_forcing(self, attr):
        easymore_output = self.project_dir / "forcing" / "basin_averaged_data"
        timeshift = self.config.get('FORCING_TIMESHIFT', 0)
        forcing_units = self.config.get('FORCING_UNITS', {})
        return write_summa_forcing(self.summa_setup_dir, timeshift, forcing_units, easymore_output, attr, self.geofabric_mapping)

    def write_summa_paramtrial(self, attr):
        write_summa_paramtrial(attr, self.summa_setup_dir)

    def write_summa_initial_conditions(self, attr):
        write_summa_initial_conditions(attr, self.config.get('SOIL_LAYER_DEPTH'), self.summa_setup_dir)

    def write_summa_filemanager(self, forcing):
        write_summa_filemanager(self.summa_setup_dir, forcing)

    def copy_summa_static_files(self):
        copy_summa_static_files(self.summa_setup_dir)

class SUMMAPostprocessor:
    """
    Postprocessor for SUMMA model outputs via MizuRoute routing.
    Handles extraction and processing of simulation results.
    """
    def __init__(self, config: Dict[str, Any], logger: Any):
        self.config = config
        self.logger = logger
        self.data_dir = Path(self.config.get('CONFLUENCE_DATA_DIR'))
        self.domain_name = self.config.get('DOMAIN_NAME')
        self.project_dir = self.data_dir / f"domain_{self.domain_name}"
        self.results_dir = self.project_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def extract_streamflow(self) -> Optional[Path]:
        try:
            self.logger.info("Extracting SUMMA/MizuRoute streamflow results")
            
            # Get simulation output path
            if self.config.get('SIMULATIONS_PATH') == 'default':
                sim_file_path = self.project_dir / 'simulations' / self.config.get('EXPERIMENT_ID') / 'mizuRoute' / f"{self.config['EXPERIMENT_ID']}.h.{self.config['FORCING_START_YEAR']}-01-01-03600.nc"
            else:
                sim_file_path = Path(self.config.get('SIMULATIONS_PATH'))
                
            if not sim_file_path.exists():
                self.logger.error(f"SUMMA/MizuRoute output file not found at: {sim_file_path}")
                return None
                
            # Get simulation reach ID
            sim_reach_ID = self.config.get('SIM_REACH_ID')
            
            # Read simulation data
            ds = xr.open_dataset(sim_file_path, engine='netcdf4')
            
            # Extract data for the specific reach
            segment_index = ds['reachID'].values == int(sim_reach_ID)
            sim_df = ds.sel(seg=segment_index)
            q_sim = sim_df['IRFroutedRunoff'].to_dataframe().reset_index()
            q_sim.set_index('time', inplace=True)
            q_sim.index = q_sim.index.round(freq='h')
            
            # Convert from hourly to daily average
            q_sim_daily = q_sim['IRFroutedRunoff'].resample('D').mean()
            
            # Read existing results file if it exists
            output_file = self.results_dir / f"{self.config['EXPERIMENT_ID']}_results.csv"
            if output_file.exists():
                results_df = pd.read_csv(output_file, index_col=0, parse_dates=True)
            else:
                results_df = pd.DataFrame(index=q_sim_daily.index)
            
            # Add SUMMA results
            results_df['SUMMA_discharge_cms'] = q_sim_daily
            
            # Save updated results
            results_df.to_csv(output_file)
            
            return output_file
            
        except Exception as e:
            self.logger.error(f"Error extracting SUMMA streamflow: {str(e)}")
            raise
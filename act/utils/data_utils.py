"""
act.utils.data_utils
--------------------

Module containing utilities for the data.

"""

import importlib

import numpy as np
import scipy.stats as stats
import xarray as xr
import pint

spec = importlib.util.find_spec('pyart')
if spec is not None:
    PYART_AVAILABLE = True
else:
    PYART_AVAILABLE = False


def assign_coordinates(ds, coord_list):
    """
    This procedure will create a new ACT dataset whose coordinates are
    designated to be the variables in a given list. This helps make data
    slicing via xarray and visualization easier.

    Parameters
    ----------
    ds : ACT Dataset
        The ACT Dataset to modify the coordinates of.
    coord_list : dict
        The list of variables to assign as coordinates, given as a dictionary
        whose keys are the variable name and values are the dimension name.

    Returns
    -------
    new_ds : ACT Dataset
        The new ACT Dataset with the coordinates assigned to be the given
        variables.

    """
    # Check to make sure that user assigned valid entries for coordinates

    for coord in coord_list.keys():
        if coord not in ds.variables.keys():
            raise KeyError(coord + " is not a variable in the Dataset.")

        if ds.dims[coord_list[coord]] != len(ds.variables[coord]):
            raise IndexError((coord + " must have the same " +
                              "value as length of " +
                              coord_list[coord]))

    new_ds_dict = {}
    for variable in ds.variables.keys():
        my_coord_dict = {}
        dataarray = ds[variable]
        if len(dataarray.dims) > 0:
            for coord in coord_list.keys():
                if coord_list[coord] in dataarray.dims:
                    my_coord_dict[coord_list[coord]] = ds[coord]

        if variable not in my_coord_dict.keys() and variable not in ds.dims:
            the_dataarray = xr.DataArray(dataarray.data, coords=my_coord_dict,
                                         dims=dataarray.dims)
            new_ds_dict[variable] = the_dataarray

    new_ds = xr.Dataset(new_ds_dict, coords=my_coord_dict)

    return new_ds


def add_in_nan(time, data):
    """
    This procedure adds in NaNs for given time periods in time when there is no
    corresponding data available. This is useful for timeseries that have
    irregular gaps in data.

    Parameters
    ----------
    time : 1D array of np.datetime64
        List of times in the timeseries.
    data : 1 or 2D array
        Array containing the data. The 0 axis corresponds to time.

    Returns
    -------
    d_time : xarray DataArray
        The xarray DataArray containing the new times at regular intervals.
        The intervals are determined by the mode of the timestep in *time*.
    d_data : xarray DataArray
        The xarray DataArray containing the NaN-filled data.

    """
    # Return if time dimension is only size one since we can't do differences.
    if time.size < 2:
        return time, data

    diff = np.diff(time, 1) / np.timedelta64(1, 's')
    mode = stats.mode(diff).mode[0]
    index = np.where(diff > 2. * mode)
    d_data = np.asarray(data)
    d_time = np.asarray(time)

    offset = 0
    for i in index[0]:
        n_obs = np.floor(
            (time[i + 1] - time[i]) / mode / np.timedelta64(1, 's'))
        time_arr = [
            d_time[i + offset] + np.timedelta64(int((n + 1) * mode), 's')
            for n in range(int(n_obs) - 1)]
        S = d_data.shape
        if len(S) == 2:
            data_arr = np.empty([len(time_arr), S[1]])
        else:
            data_arr = np.empty([len(time_arr)])
        data_arr[:] = np.nan

        d_time = np.insert(d_time, i + 1 + offset, time_arr)
        d_data = np.insert(d_data, i + 1 + offset, data_arr, axis=0)
        offset += len(time_arr)

    d_time = xr.DataArray(d_time)
    d_data = xr.DataArray(d_data)

    return d_time, d_data


def get_missing_value(data_object, variable, default=-9999,
                      add_if_missing_in_obj=False,
                      use_FillValue=False, nodefault=False):
    """
    Function to get missing value from missing_value or _FillValue attribute.
    Works well with catching errors and allows for a default value when a
    missing value is not listed in the object. You may get strange results
    becaus xarray will automatically convert all missing_value or
    _FillValue to NaN and then remove the missing_value and
    _FillValue variable attribute when reading data with default settings.

    Parameters
    ----------
    data_object : xarray dataset
        Xarray dataset containing data variable.
    variable : str
        Variable name to use for getting missing value.
    default : int or float
        Default value to use if missing value attribute is not in data object.
    add_if_missing_in_obj : bool
        Boolean to add to object if does not exist. Default is False.
    use_FillValue : bool
        Boolean to use _FillValue instead of missing_value. If missing_value
        does exist and _FillValue does not will add _FillValue
        set to missing_value value.
    nodefault : bool
        Option to use this to check if the varible has a missing value set and
        do not want to get default as return. If the missing value is found
        will return, else will return None.

    Returns
    -------
    missing : scalar int or float (or None)
        Value used to indicate missing value matching type of data or None if
        nodefault keyword set to True.

    Examples
    --------
    .. code-block:: python

        from act.utils import get_missing_value
        missing = get_missing_value(dq_object, 'temp_mean')
        print(missing)
        -9999.0

    """
    in_object = False
    if use_FillValue:
        missing_atts = ['_FillValue', 'missing_value']
    else:
        missing_atts = ['missing_value', '_FillValue']

    for att in missing_atts:
        try:
            missing = data_object[variable].attrs[att]
            in_object = True
            break
        except (AttributeError, KeyError):
            missing = default

    # Check if do not want a default value retured and a value
    # was not fund.
    if nodefault is True and in_object is False:
        missing = None
        return missing

    # Check data type and try to match missing_value to the data type of data
    try:
        missing = data_object[variable].data.dtype.type(missing)
    except KeyError:
        pass
    except AttributeError:
        print(('--- AttributeError: Issue trying to get data type ' +
               'from "{}" data ---').format(variable))

    # If requested add missing value to object
    if add_if_missing_in_obj and not in_object:
        try:
            data_object[variable].attrs[missing_atts[0]] = missing
        except KeyError:
            print(('---  KeyError: Issue trying to add "{}" ' +
                   'attribute to "{}" ---').format(missing_atts[0], variable))

    return missing


def convert_units(data, in_units, out_units):
    """
    Wrapper function around library to convert data using unit strings.
    Currently using pint units library. Will attempt to preserve numpy
    data type, but will upconvert to numpy float64 if need to change
    data type for converted values.

    Parameters
    ----------
    data : list, tuple or numpy array
        Data array to be modified.
    in_units : str
        Units scalar string of input data array.
    out_units : str
        Units scalar string of desired output data array.

    Returns
    -------
    data : numpy array
        Data array converted into new units.

    Examples
    --------
    > data = np.array([1,2,3,4,5,6])
    > data = convert_units(data, 'cm', 'm')
    > data
    array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])


    """
    # Fix historical and current incorrect usage of units.
    convert_dict = {
        'C': 'degC',
        'F': 'degF',
        '%': 'percent',  # seems like pint does not like this symbol?
        '1': 'unitless',  # seems like pint does not like this number?
    }

    if in_units in convert_dict:
        in_units = convert_dict[in_units]

    if out_units in convert_dict:
        out_units = convert_dict[out_units]

    if in_units == out_units:
        return data

    # Instantiate the registry
    ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)

    # Add missing units
    ureg.define('percent = 0.01*count = %')
    ureg.define('unitless = count = 1')

    if not isinstance(data, np.ndarray):
        data = np.array(data)

    data_type = data.dtype
    data_type_kind = data.dtype.kind

    # Do the conversion magic
    data = np.asarray((data * ureg(in_units)).to(out_units))

    # The data type may be changed by pint. This is a side effect
    # of pint changing the datatype to float. Check if the converted values
    # need float precision. If so leave, if not change back to orginal
    # precision after checking if the precsion is not lost with the orginal
    # data type.
    if (data_type_kind == 'i' and
            np.nanmin(data) >= np.iinfo(data_type).min and
            np.nanmax(data) <= np.iinfo(data_type).max and
            np.all(np.mod(data, 1) == 0)):
        data = data.astype(data_type)

    return data


def ts_weighted_average(ts_dict):
    """
    Program to take in multiple difference time-series and average them
    using the weights provided. This assumes that the variables passed in
    all have the same units. Please see example gallery for an example.

    NOTE: All weights should add up to 1

    Parameters
    ----------
    ts_dict : dict
        Dictionary containing datastream, variable, weight, and objects

        .. code-block:: python

            t_dict = {'sgpvdisC1.b1': {'variable': 'rain_rate', 'weight': 0.05,
                                       'object': act_obj}
                      'sgpmetE13.b1': {'variable': ['tbrg_precip_total',
                                       'org_precip_rate_mean',
                                       'pwd_precip_rate_mean_1min'],
                                       'weight': [0.25, 0.05, 0.0125]}}

    Returns
    -------
    data : numpy array
        Variable of time-series averaged data

    """

    # Run through each datastream/variable and get data
    da_array = []
    data = 0.
    for d in ts_dict:
        for i, v in enumerate(ts_dict[d]['variable']):
            new_name = '_'.join([d, v])
            # Since many variables may have same name, rename with datastream
            da = ts_dict[d]['object'][v].rename(new_name)

            # Apply Weights to Data
            da.values = da.values * ts_dict[d]['weight'][i]
            da_array.append(da)

    da = xr.merge(da_array)

    # Stack all the data into a 2D time series
    data = None
    for i, d in enumerate(da):
        if i == 0:
            data = da[d].values
        else:
            data = np.vstack((data, da[d].values))

    # Sum data across each time sample
    data = np.nansum(data, 0)

    # Add data to data array and return
    dims = ts_dict[list(ts_dict.keys())[0]]['object'].dims
    da_xr = xr.DataArray(data, dims=dims,
                         coords={'time': ts_dict[list(ts_dict.keys())[0]]['object']['time']})
    da_xr.attrs['long_name'] = 'Weighted average of ' + ', '.join(list(ts_dict.keys()))

    return da_xr


def accumulate_precip(act_obj, variable, time_delta=None):
    """
    Program to accumulate rain rates from an act object and insert variable back
    into act object with "_accumulated" appended to the variable name. Please
    verify that your units are accurately described in the data.

    Parameters
    ----------
    act_obj : xarray DataSet
        ACT Object.
    variable : string
        Variable name
    time_delta : float
        Time delta to caculate precip accumulations over.
        Useful if full time series is not passed in

    Returns
    -------
    act_obj : xarray DataSet
        ACT object with variable_accumulated.

    """
    # Get Data, time, and metadat
    data = act_obj[variable]
    time = act_obj.coords['time']
    units = act_obj[variable].attrs['units']

    # Calculate mode of the time samples(i.e. 1 min vs 1 sec)
    if time_delta is None:
        diff = np.diff(time.values, 1) / np.timedelta64(1, 's')
        t_delta = stats.mode(diff).mode
    else:
        t_delta = time_delta

    # Calculate the accumulation based on the units
    t_factor = t_delta / 60.
    if units == 'mm/hr':
        data = data * (t_factor / 60.)

    accum = np.cumsum(data.values)

    # Add time as a variable if not already a variable
    if 'time' not in act_obj:
        act_obj['time'] = xr.DataArray(time, coords=act_obj[variable].coords)

    # Add accumulated variable back to ACT object
    long_name = 'Accumulated precipitation'
    attrs = {'long_name': long_name, 'units': 'mm'}
    act_obj['_'.join([variable, 'accumulated'])] = xr.DataArray(accum, coords=act_obj[variable].coords,
                                                                attrs=attrs)

    return act_obj


def create_pyart_obj(obj, variables=None, sweep=None, azimuth=None, elevation=None,
                     range_var=None, sweep_start=None, sweep_end=None, lat=None, lon=None,
                     alt=None, sweep_mode='ppi'):
    """
    Produces a PyART radar object based on data in the ACT object

    Parameters
    ----------
    obj : xarray DataSet
        ACT Object.
    variables : list
        List of variables to add to the radar object, will default to all variables
    sweep : string
        Name of variable that has sweep information.  If none, will try and calculate
        from the azimuth and elevation
    azimuth : string
        Name of azimuth variable.  Will try and find one if none given
    elevation : string
        Name of elevation variable.  Will try and find one if none given
    range_var : string
        Name of the range variable. Will try and find one if none given
    sweep_start : string
        Name of variable with sweep start indices
    sweep_end : string
        Name of variable with sweep end indices
    lat : string
        Name of latitude variable.  Will try and find one if none given
    lon : string
        Name of longitude variable.  Will try and find one if none given
    alt : string
        Name of altitude variable.  Will try and find one if none given
    sweep_mode : string
        Type of scan.  Defaults to PPI

    Returns
    -------
    radar : PyART Object
        PyART Radar Object

    """

    if not PYART_AVAILABLE:
        raise ImportError("PyART needs to be installed on your system to convert to PyART Object")
    else:
        import pyart
    # Get list of variables if none provided
    if variables is None:
        variables = list(obj.keys())

    # Determine the sweeps if not already in a variable$a
    if sweep is None:
        swp = np.zeros(obj.sizes['time'])
    else:
        swp = obj[sweep].values

    # Get coordinate variables
    if lat is None:
        lat = [s for s in variables if "latitude" in s][0]
        if len(lat) == 0:
            lat = [s for s in variables if "lat" in s][0]
        if len(lat) == 0:
            raise ValueError("Latitude variable not set and could not be discerned from the data")

    if lon is None:
        lon = [s for s in variables if "longitude" in s][0]
        if len(lon) == 0:
            lon = [s for s in variables if "lon" in s][0]
        if len(lon) == 0:
            raise ValueError("Longitude variable not set and could not be discerned from the data")

    if alt is None:
        alt = [s for s in variables if "altitude" in s][0]
        if len(alt) == 0:
            alt = [s for s in variables if "alt" in s][0]
        if len(alt) == 0:
            raise ValueError("Altitude variable not set and could not be discerned from the data")

    # Get additional variable names if none provided
    if azimuth is None:
        azimuth = [s for s in sorted(variables) if "azimuth" in s][0]
        if len(azimuth) == 0:
            raise ValueError("Azimuth variable not set and could not be discerned from the data")

    if elevation is None:
        elevation = [s for s in sorted(variables) if "elevation" in s][0]
        if len(elevation) == 0:
            raise ValueError("Elevation variable not set and could not be discerned from the data")

    if range_var is None:
        range_var = [s for s in sorted(variables) if "range" in s][0]
        if len(range_var) == 0:
            raise ValueError("Range variable not set and could not be discerned from the data")

    # Calculate the sweep indices if not passed in
    if sweep_start is None and sweep_end is None:
        az_diff = np.abs(np.diff(obj[azimuth].values))
        az_idx = (az_diff > 10.)

        el_diff = np.abs(np.diff(obj[elevation].values))
        el_idx = (el_diff > 0.5)

        # Create index list
        az_index = list(np.where(az_idx)[0] + 1)
        el_index = list(np.where(el_idx)[0] + 1)
        index = sorted(az_index + el_index)

        index.insert(0, 0)
        index += [obj.sizes['time']]

        sweep_start_index = []
        sweep_end_index = []
        for i in range(len(index) - 1):
            sweep_start_index.append(index[i])
            sweep_end_index.append(index[i + 1] - 1)
            swp[index[i]:index[i + 1]] = i
    else:
        sweep_start_index = obj[sweep_start].values
        sweep_end_index = obj[sweep_end].values
        if sweep is None:
            for i in range(len(sweep_start_index)):
                swp[sweep_start_index[i]:sweep_end_index[i]] = i

    radar = pyart.testing.make_empty_ppi_radar(obj.sizes[range_var], obj.sizes['time'], len(sweep_start_index) - 1)

    radar.time['data'] = np.array(obj['time'].values)

    # Add lat, lon, alt
    radar.latitude['data'] = np.array(obj[lat].values)
    radar.longitude['data'] = np.array(obj[lon].values)
    radar.altitude['data'] = np.array(obj[alt])

    # Add sweep information
    radar.sweep_number['data'] = sweep
    radar.sweep_start_ray_index['data'] = sweep_start_index
    radar.sweep_end_ray_index['data'] = sweep_end_index
    radar.sweep_mode['data'] = np.array(sweep_mode)

    # Add elevation, azimuth, etc...
    radar.azimuth['data'] = np.array(obj[azimuth])
    radar.elevation['data'] = np.array(obj[elevation])
    radar.fixed_angle['data'] = np.array(obj[elevation].values[0])
    radar.range['data'] = np.array(obj[range_var].values)

    # Calculate radar points in lat/lon
    radar.init_gate_altitude()
    radar.init_gate_longitude_latitude()

    # Add the fields to the radar object
    fields = {}
    for v in variables:
        ref_dict = pyart.config.get_metadata(v)
        ref_dict['data'] = np.array(obj[v].values)
        fields[v] = ref_dict
    radar.fields = fields

    return radar

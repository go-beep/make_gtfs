import json
from pathlib import Path

import pandas as pd
import numpy as np
import shapely.ops as so
import shapely.geometry as sg
import utm
import gtfstk as gt

from . import constants as cs


class ProtoFeed(object):
    """
    An ProtoFeed instance holds the source data
    from which to build a GTFS feed, plus a little metadata.

    Attributes are

    - ``service_windows``: DataFrame
    - ``frequencies``: DataFrame; has speeds filled in
    - ``meta``: DataFrame
    - ``shapes``: dictionary
    - ``shapes_extra``: dictionary of the form <shape ID> ->
      <trip directions using the shape (0, 1, or 2)>
    """

    def __init__(self, frequencies=None, meta=None, service_windows=None,
      shapes=None, stops=None):

        self.frequencies = frequencies
        self.meta = meta
        self.service_windows = service_windows
        self.shapes = shapes
        self.stops = stops

        # Clean frequencies
        freq = self.frequencies
        if freq is not None:
            cols = freq.columns

            # Fill missing route types with 3 (bus)
            freq['route_type'].fillna(3, inplace=True)
            freq['route_type'] = freq['route_type'].astype(int)

            # Create route speeds and fill in missing values with default speeds
            if 'speed' not in cols:
                freq['speed'] = np.nan
            freq['speed'].fillna(self.meta['default_route_speed'].iat[0],
              inplace=True)

        self.frequencies = freq

        # Build shapes extra from shape IDs in frequencies
        if self.frequencies is not None:
            def my_agg(group):
                d = {}
                dirs = group.direction.unique()
                if len(dirs) > 1 or 2 in dirs:
                    d['direction'] = 2
                else:
                    d['direction'] = dirs[0]
                return pd.Series(d)

            self.shapes_extra = dict(
                self.frequencies
                .groupby('shape_id')
                .apply(my_agg)
                .reset_index()
                .values
            )
        else:
            self.shapes_extra = None

    def copy(self):
        """
        Return a copy of this ProtoFeed, that is, a feed with all the
        same attributes.
        """
        other = ProtoFeed()
        for key in cs.PROTOFEED_ATTRS:
            value = getattr(self, key)
            if isinstance(value, pd.DataFrame):
                # Pandas copy DataFrame
                value = value.copy()
            setattr(other, key, value)

        return other

def read_protofeed(path):
    """
    Read the data files at the given directory path
    (string or Path object) that specify a ProtoFeed.
    Return the resulting ProtoFeed.

    The data files are

    - ``frequencies.csv``: (required) A CSV file containing route frequency
      information. The CSV file contains the columns

      - ``route_short_name``: (required) String. A unique short name
        for the route, e.g. '51X'
      - ``route_long_name``: (required) String. Full name of the route
        that is more descriptive than ``route_short_name``
      - ``route_type``: (required) Integer. The
        `GTFS type of the route <https://developers.google.com/transit/gtfs/reference/#routestxt>`_
      - ``service_window_id`` (required): String. A service window ID
        for the route taken from the file ``service_windows.csv``
      - ``direction``: (required) Integer 0, 1, or 2. Indicates
        whether the route travels in GTFS direction 0, GTFS direction
        1, or in both directions.
        In the latter case, trips will be created that travel in both
        directions along the route's path, each direction operating at
        the given frequency.  Otherwise, trips will be created that
        travel in only the given direction.
      - ``frequency`` (required): Integer. The frequency of the route
        during the service window in vehicles per hour.
      - ``speed``:  (optional) Float. The speed of the route in
        kilometers per hour
      - ``shape_id``: (required) String. A shape ID that is listed in
        ``shapes.geojson`` and corresponds to the linestring of the
        (route, direction, service window) tuple.

    - ``meta.csv``: (required) A CSV file containing network metadata.
      The CSV file contains the columns

      - ``agency_name``: (required) String. The name of the transport
        agency
      - ``agency_url``: (required) String. A fully qualified URL for
        the transport agency
      - ``agency_timezone``: (required) String. Timezone where the
        transit agency is located. Timezone names never contain the
        space character but may contain an underscore. Refer to
        `http://en.wikipedia.org/wiki/List_of_tz_zones <http://en.wikipedia.org/wiki/List_of_tz_zones>`_ for a list of valid values
      - ``start_date``, ``end_date`` (required): Strings. The start
        and end dates for which all this network information is valid
        formated as YYYYMMDD strings
      - ``default_route_speed``: (required) Float. Default speed in
        kilometers per hour to assign to routes with no ``speed``
        entry in the file ``routes.csv``

    - ``service_windows.csv``: (required) A CSV file containing service window
      information.
      A *service window* is a time interval and a set of days of the
      week during which all routes have constant service frequency,
      e.g. Saturday and Sunday 07:00 to 09:00.
      The CSV file contains the columns

      - ``service_window_id``: (required) String. A unique identifier
        for a service window
      - ``start_time``, ``end_time``: (required) Strings. The start
        and end times of the service window in HH:MM:SS format where
        the hour is less than 24
      - ``monday``, ``tuesday``, ``wednesday``, ``thursday``,
        ``friday``, ``saturday``, ``sunday`` (required): Integer 0
        or 1. Indicates whether the service is active on the given day
        (1) or not (0)

    - ``shapes.geojson``: (required) A GeoJSON file containing route shapes.
      The file consists of one feature collection of LineString
      features, where each feature's properties contains at least the
      attribute ``shape_id``, which links the route's shape to the
      route's information in ``routes.csv``.

    - ``stops.csv``: (optional) A CSV file containing all the required
      and optional fields of ``stops.txt`` in
      `the GTFS <https://developers.google.com/transit/gtfs/reference/#stopstxt>`_

    """
    path = Path(path)

    service_windows = pd.read_csv(
      path/'service_windows.csv')

    meta = pd.read_csv(path/'meta.csv',
      dtype={'start_date': str, 'end_date': str})

    with (path/'shapes.geojson').open() as src:
        shapes = json.load(src)

    if (path/'stops.csv').exists():
        stops = (
            pd.read_csv(path/'stops.csv', dtype={
                'stop_id': str,
                'stop_code': str,
                'zone_id': str,
                'location_type': int,
                'parent_station': str,
                'stop_timezone': str,
                'wheelchair_boarding': int,
            })
            .drop_duplicates(subset=['stop_lon', 'stop_lat'])
            .dropna(subset=['stop_lon', 'stop_lat'], how='any')
        )
    else:
        stops = None

    frequencies = pd.read_csv(path/'frequencies.csv', dtype={
        'route_short_name': str,
        'service_window_id': str,
        'shape_id': str,
        'direction': int,
        'frequency': int,
    })

    return ProtoFeed(frequencies, meta, service_windows, shapes, stops)

def get_duration(timestr1, timestr2, units='s'):
    """
    Return the duration of the time period between the first and second
    time string in the given units.
    Allowable units are 's' (seconds), 'min' (minutes), 'h' (hours).
    Assume ``timestr1 < timestr2``.
    """
    valid_units = ['s', 'min', 'h']
    assert units in valid_units,\
      "Units must be one of {!s}".format(valid_units)

    duration = (
        gt.timestr_to_seconds(timestr2) - gt.timestr_to_seconds(timestr1)
    )

    if units == 's':
        return duration
    elif units == 'min':
        return duration/60
    else:
        return duration/3600

def build_stop_ids(shape_id):
    """
    Create a pair of stop IDs based on the given shape ID.
    """
    return [cs.SEP.join(['stp', shape_id, str(i)]) for i in range(2)]

def build_stop_names(shape_id):
    """
    Create a pair of stop names based on the given shape ID.
    """
    return ['Stop {!s} on shape {!s} '.format(i, shape_id)
      for i in range(2)]

def build_agency(pfeed):
    """
    Given a ProtoFeed, return a DataFrame representing ``agency.txt``
    """
    return pd.DataFrame({
      'agency_name': pfeed.meta['agency_name'].iat[0],
      'agency_url': pfeed.meta['agency_url'].iat[0],
      'agency_timezone': pfeed.meta['agency_timezone'].iat[0],
    }, index=[0])

def build_calendar_etc(pfeed):
    """
    Given a ProtoFeed, return a DataFrame representing ``calendar.txt``
    and a dictionary of the form <service window ID> -> <service ID>,
    respectively.
    """
    windows = pfeed.service_windows.copy()

    # Create a service ID for each distinct days_active field and map the
    # service windows to those service IDs
    def get_sid(bitlist):
        return 'srv' + ''.join([str(b) for b in bitlist])

    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday',
      'saturday', 'sunday']
    bitlists = set()

    # Create a dictionary <service window ID> -> <service ID>
    d = dict()
    for index, window in windows.iterrows():
        bitlist = window[weekdays].tolist()
        d[window['service_window_id']] = get_sid(bitlist)
        bitlists.add(tuple(bitlist))
    service_by_window = d

    # Create calendar
    start_date = pfeed.meta['start_date'].iat[0]
    end_date = pfeed.meta['end_date'].iat[0]
    F = []
    for bitlist in bitlists:
        F.append([get_sid(bitlist)] + list(bitlist) +
          [start_date, end_date])
    calendar = pd.DataFrame(F, columns=(
      ['service_id'] + weekdays + ['start_date', 'end_date']))

    return calendar, service_by_window

def build_routes(pfeed):
    """
    Given a ProtoFeed, return a DataFrame representing ``routes.txt``.
    """
    f = pfeed.frequencies[['route_short_name', 'route_long_name',
      'route_type', 'shape_id']].drop_duplicates().copy()

    # Create route IDs
    f['route_id'] = 'r' + f['route_short_name'].map(str)

    del f['shape_id']

    return f

def build_geometry_by_shape(pfeed, *, use_utm=False):
    """
    Given a ProtoFeed, return a dictionary of the form
    <shape ID> -> <Shapely linestring of shape>
    build from ``pfeed.shapes``.
    Warning: this could contain more shapes than are referenced
    in ``pfeed.frequencies``.

    If ``use_utm``, then return each linestring in in UTM coordinates.
    Otherwise, return each linestring in WGS84 longitude-latitude
    coordinates.
    """
    # Note the output for conversion to UTM with the utm package:
    # >>> u = utm.from_latlon(47.9941214, 7.8509671)
    # >>> print u
    # (414278, 5316285, 32, 'T')
    if use_utm:
        def proj(lon, lat):
            return utm.from_latlon(lat, lon)[:2]
    else:
        def proj(lon, lat):
            return lon, lat

    return {f['properties']['shape_id']:
      so.transform(proj, sg.shape(f['geometry']))
      for f in pfeed.shapes['features']}

def build_shapes(pfeed):
    """
    Given a ProtoFeed, return DataFrame representing ``shapes.txt``.
    Only use shape IDs that occur in both ``pfeed.shapes`` and
    ``pfeed.frequencies``.
    Create reversed shapes where routes traverse shapes in both
    directions.
    """
    rows = []
    geometry_by_shape = build_geometry_by_shape(pfeed)
    for shape, geom in geometry_by_shape.items():
        if shape not in pfeed.shapes_extra:
            continue
        if pfeed.shapes_extra[shape] == 2:
            # Add shape and its reverse
            shid = shape + '-1'
            new_rows = [[shid, i, lon, lat]
              for i, (lon, lat) in enumerate(geom.coords)]
            rows.extend(new_rows)
            shid = shape + '-0'
            new_rows = [[shid, i, lon, lat]
              for i, (lon, lat) in enumerate(reversed(geom.coords))]
            rows.extend(new_rows)
        else:
            # Add shape
            shid = '{}{}{}'.format(shape, cs.SEP, pfeed.shapes_extra[shape])
            new_rows = [[shid, i, lon, lat]
              for i, (lon, lat) in enumerate(geom.coords)]
            rows.extend(new_rows)

    return pd.DataFrame(rows, columns=['shape_id', 'shape_pt_sequence',
      'shape_pt_lon', 'shape_pt_lat'])

def build_stops(pfeed, shapes=None):
    """
    Given a ProtoFeed, return a DataFrame representing ``stops.txt``.
    If ``pfeed.stops`` is not ``None``, then return that.
    Otherwise, require built shapes output by :func:`build_shapes`,
    create one stop at the beginning (the first point) of each shape
    and one at the end (the last point) of each shape, and
    only create stops for shape IDs that are listed in both
    ``frequencies.csv`` and ``shapes.geojson``.
    """
    if pfeed.stops is not None:
        stops = pfeed.stops.copy()
    else:
        if shapes is None:
            raise ValueError('Must input shapes built by build_shapes()')

        geo_shapes = gt.geometrize_shapes(shapes)
        rows = []
        for shape, linestring in geo_shapes[['shape_id',
          'geometry']].itertuples(index=False):
            stop_ids = build_stop_ids(shape)
            stop_names = build_stop_names(shape)
            for i in range(2):
                stop_id = stop_ids[i]
                stop_name = stop_names[i]
                stop_lon, stop_lat = linestring.interpolate(i,
                  normalized=True).coords[0]
                rows.append([stop_id, stop_name, stop_lon, stop_lat])

        stops = pd.DataFrame(rows, columns=['stop_id', 'stop_name',
          'stop_lon', 'stop_lat'])

    return stops

def build_trips(pfeed, routes, service_by_window):
    """
    Given a ProtoFeed and its corresponding routes (DataFrame),
    service-by-window (dictionary), return a DataFrame representing
    ``trips.txt``.
    Trip IDs encode route, direction, and service window information
    to make it easy to compute stop times later.
    """
    # Put together the route and service data
    routes = pd.merge(routes[['route_id', 'route_short_name']],
      pfeed.frequencies)
    routes = pd.merge(routes, pfeed.service_windows)

    # For each row in routes, add trips at the specified frequency in
    # the specified direction
    rows = []
    for index, row in routes.iterrows():
        shape = row['shape_id']
        route = row['route_id']
        window = row['service_window_id']
        start, end = row[['start_time', 'end_time']].values
        duration = get_duration(start, end, 'h')
        frequency = row['frequency']
        if not frequency:
            # No trips during this service window
            continue
        # Rounding down occurs here if the duration isn't integral
        # (bad input)
        num_trips_per_direction = int(frequency*duration)
        service = service_by_window[window]
        direction = row['direction']
        if direction == 2:
            directions = [0, 1]
        else:
            directions = [direction]
        for direction in directions:
            # Warning: this shape-ID-making logic needs to match that
            # in ``build_shapes``
            shid = '{}{}{}'.format(shape, cs.SEP, direction)
            rows.extend([[
              route,
              cs.SEP.join(['t', route, window, start,
              str(direction), str(i)]),
              direction,
              shid,
              service
            ] for i in range(num_trips_per_direction)])

    return pd.DataFrame(rows, columns=['route_id', 'trip_id', 'direction_id',
      'shape_id', 'service_id'])

def get_nearby_stops(geo_stops, linestring, side, buffer=cs.BUFFER):
    """
    Given a GeoDataFrame of stops in a meters-based coordinate system,
    a Shapely LineString in a meters-based coordinate system,
    a side of the LineString (string; 'left' = left hand side of
    LineString, 'right' = right hand side of LineString, or
    'both' = both sides), do the following.
    Return a GeoDataFrame of all the stops that lie within
    ``buffer`` meters to the ``side`` of the LineString.
    """
    # Buffer linestring
    b = linestring.buffer(buffer, cap_style=2)
    if side != 'both':
        # Make a tiny buffer to split the normal-size buffer
        # in half across the linestring
        b0 = linestring.buffer(0.5, cap_style=3)
        diff = b.difference(b0)
        polys = so.polygonize(diff)
        if side == 'left':
            b = list(polys)[0]
        else:
            b = list(polys)[1]

    # Collect stops
    return geo_stops.loc[geo_stops.intersects(b)].copy()

def build_stop_times(pfeed, routes, shapes, trips, buffer=cs.BUFFER):
    """
    Given a ProtoFeed and its corresponding routes (DataFrame),
    shapes (DataFrame), stops (DataFrame), trips (DataFrame),
    return DataFrame representing ``stop_times.txt``.
    Includes the optional ``shape_dist_traveled`` column.
    """
    # Get the table of trips and add frequency and service window details
    routes = (
        routes
        .filter(['route_id', 'route_short_name'])
        .merge(pfeed.frequencies.drop(['shape_id'], axis=1))
    )
    trips = (
        trips
        .assign(service_window_id=lambda x: x.trip_id.map(
          lambda y: y.split(cs.SEP)[2]))
        .merge(routes)
    )

    # Get the geometries of ``shapes`` and not ``pfeed.shapes``
    geometry_by_shape = dict(
        gt.geometrize_shapes(shapes, use_utm=True)
        .filter(['shape_id', 'geometry'])
        .values
    )

    # Save on distance computations by memoizing
    dist_by_stop_by_shape = {shape: {} for shape in geometry_by_shape}

    def compute_stops_dists_times(geo_stops, linestring, shape,
      start_time, end_time):
        """
        Given a GeoDataFrame of stops on one side of a given Shapely
        LineString with given shape ID, compute distances and departure
        times of a trip traversing the LineString from start to end
        at the given start and end times (in seconds past midnight)
        and stoping at the stops encountered along the way.
        Do not assume that the stops are ordered by trip encounter.
        Return three lists of the same length: the stop IDs in order
        that the trip encounters them, the shape distances traveled
        along distances at the stops, and the times the stops are
        encountered, respectively.
        """
        g = geo_stops.copy()
        dists_and_stops = []
        for i, stop in enumerate(g['stop_id'].values):
            if stop in dist_by_stop_by_shape[shape]:
                d = dist_by_stop_by_shape[shape][stop]
            else:
                d = gt.get_segment_length(linestring,
                  g.geometry.iat[i])/1000  # km
                dist_by_stop_by_shape[shape][stop] = d
            dists_and_stops.append((d, stop))
        dists, stops = zip(*sorted(dists_and_stops))
        D = linestring.length/1000
        dists_are_reasonable = all([d < D + 100 for d in dists])
        if not dists_are_reasonable:
            # Assume equal distances between stops :-(
            n = len(stops)
            delta = D/(n - 1)
            dists = [i*delta for i in range(n)]

        # Compute times using distances, start and end stop times,
        # and linear interpolation
        t0, t1 = start_time, end_time
        d0, d1 = dists[0], dists[-1]
        # Interpolate
        times = np.interp(dists, [d0, d1], [t0, t1])
        return stops, dists, times

    # Iterate through trips and set stop times based on stop ID
    # and service window frequency.
    # Remember that every trip has a valid shape ID.
    rows = []
    if pfeed.stops is None:
        # Trip has only two stops, one at each path endpoint
        for index, row in trips.iterrows():
            shape = row['shape_id']
            length = geometry_by_shape[shape].length/1000  # km
            speed = row['speed']  # km/h
            duration = int((length/speed)*3600)  # seconds
            frequency = row['frequency']
            if not frequency:
                # No stop times for this trip/frequency combo
                continue
            headway = 3600/frequency  # seconds
            trip = row['trip_id']
            __, route, window, base_timestr, direction, i =\
              trip.split(cs.SEP)
            direction = int(direction)
            stop_ids = build_stop_ids(shape)
            # if direction == 1:
            #     stop_ids.reverse()
            base_time = gt.timestr_to_seconds(base_timestr)
            start_time = base_time + headway*int(i)
            end_time = start_time + duration
            new_rows = [
                [trip, stop_ids[0], 0, start_time, start_time, 0],
                [trip, stop_ids[1], 1, end_time, end_time, length],
            ]
            rows.extend(new_rows)
    else:
        # Trip has multiple stops found in ``pfeed.stops``
        geo_stops = gt.geometrize_stops(pfeed.stops, use_utm=True)
        # Look on the side of the street that traffic moves for this timezone
        side = cs.traffic_by_timezone[pfeed.meta.agency_timezone.iat[0]]
        for index, row in trips.iterrows():
            shape = row['shape_id']
            geom = geometry_by_shape[shape]
            stops = get_nearby_stops(geo_stops, geom, side, buffer=buffer)
            length = geom.length/1000  # km
            speed = row['speed']  # km/h
            duration = int((length/speed)*3600)  # seconds
            frequency = row['frequency']
            if not frequency:
                # No stop times for this trip/frequency combo
                continue
            headway = 3600/frequency  # seconds
            trip = row['trip_id']
            __, route, window, base_timestr, direction, i = (
              trip.split(cs.SEP))
            direction = int(direction)
            base_time = gt.timestr_to_seconds(base_timestr)
            start_time = base_time + headway*int(i)
            end_time = start_time + duration
            stops, dists, times = compute_stops_dists_times(stops, geom, shape,
              start_time, end_time)
            new_rows = [[trip, stop, j, time, time, dist]
              for j, (stop, time, dist) in enumerate(zip(stops, times, dists))]
            rows.extend(new_rows)

    g = pd.DataFrame(rows, columns=['trip_id', 'stop_id', 'stop_sequence',
      'arrival_time', 'departure_time', 'shape_dist_traveled'])

    # Convert seconds back to time strings
    g[['arrival_time', 'departure_time']] =\
      g[['arrival_time', 'departure_time']].applymap(
      lambda x: gt.timestr_to_seconds(x, inverse=True))

    return g

def build_feed(pfeed, buffer=cs.BUFFER):
    # Create Feed tables
    agency = build_agency(pfeed)
    calendar, service_by_window = build_calendar_etc(pfeed)
    routes = build_routes(pfeed)
    shapes = build_shapes(pfeed)
    stops = build_stops(pfeed, shapes)
    trips = build_trips(pfeed, routes, service_by_window)
    stop_times = build_stop_times(pfeed, routes, shapes, trips, buffer=buffer)

    # Remove stops that are not in stop times
    stops = stops[stops.stop_id.isin(stop_times.stop_id)].copy()

    # Create Feed
    return gt.Feed(agency=agency, calendar=calendar, routes=routes,
      shapes=shapes, stops=stops, stop_times=stop_times, trips=trips,
      dist_units='km')